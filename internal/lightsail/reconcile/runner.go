// Package reconcile applies a computed Lightsail capacity plan sequentially.
package reconcile

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/mhsanaei/3x-ui/v3/internal/lightsail/awswrite"
	"github.com/mhsanaei/3x-ui/v3/internal/lightsail/plan"
)

// Operations is intentionally narrow so tests never need AWS credentials.
type Operations interface {
	ListInstances(context.Context, string) ([]awswrite.Instance, error)
	CreateInstance(context.Context, awswrite.CreateSpec) error
	DeleteManagedInstance(context.Context, string, string, awswrite.Owner) error
}

type RunOptions struct {
	Config                   plan.Config
	AvailabilityZoneByRegion map[string]string
	Now                      func() time.Time
}

type Runner struct {
	ops Operations
	mu  sync.Mutex
}

func NewRunner(ops Operations) *Runner {
	return &Runner{ops: ops}
}

// Run reads each configured region completely before applying actions. It stops
// on the first error so a partial lifecycle change cannot cascade unchecked.
func (r *Runner) Run(ctx context.Context, options RunOptions) error {
	if r == nil || r.ops == nil {
		return errors.New("Lightsail reconciliation operations are unavailable")
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	if err := ctx.Err(); err != nil {
		return err
	}
	if strings.TrimSpace(options.Config.AccountID) == "" || strings.TrimSpace(options.Config.ProfileName) == "" {
		return errors.New("Lightsail account and named profile are required")
	}
	if _, err := plan.Plan(options.Config, nil); err != nil {
		return err
	}

	regions := append([]plan.RegionTarget(nil), options.Config.Regions...)
	sort.Slice(regions, func(i, j int) bool { return regions[i].Region < regions[j].Region })
	instances := make([]plan.Instance, 0)
	for _, target := range regions {
		if err := ctx.Err(); err != nil {
			return err
		}
		listed, err := r.ops.ListInstances(ctx, target.Region)
		if err != nil {
			return operationError("list instances", target.Region)
		}
		for _, instance := range listed {
			instances = append(instances, plan.Instance{
				ID: instance.Name, Region: instance.Region, CreatedAt: instance.CreatedAt,
				Status: instance.State,
				Tags:   instance.Tags,
			})
		}
	}
	actions, err := plan.Plan(options.Config, instances)
	if err != nil {
		return err
	}
	now := time.Now
	if options.Now != nil {
		now = options.Now
	}
	sequenceByRegion := make(map[string]int)
	for _, instance := range instances {
		sequenceByRegion[instance.Region]++
	}
	for _, action := range actions {
		if err := ctx.Err(); err != nil {
			return err
		}
		switch action.Kind {
		case plan.Create:
			zone := strings.TrimSpace(action.AvailabilityZone)
			if zone == "" {
				zone = strings.TrimSpace(options.AvailabilityZoneByRegion[action.Region])
			}
			if zone == "" {
				return fmt.Errorf("Lightsail availability zone is required for %s", action.Region)
			}
			sequenceByRegion[action.Region]++
			request := awswrite.CreateSpec{
				Region: action.Region, AvailabilityZone: zone,
				Name:     instanceName(action.Region, now(), sequenceByRegion[action.Region]),
				BundleID: action.BundleID, BlueprintID: action.BlueprintID,
				AccountID: options.Config.AccountID, ProfileName: options.Config.ProfileName,
			}
			if err := r.ops.CreateInstance(ctx, request); err != nil {
				return operationError("create instance", action.Region)
			}
		case plan.Delete:
			if err := r.ops.DeleteManagedInstance(ctx, action.Region, action.InstanceID, awswrite.Owner{
				AccountID: options.Config.AccountID, ProfileName: options.Config.ProfileName,
			}); err != nil {
				return operationError("delete instance", action.Region)
			}
		default:
			return errors.New("Lightsail reconciliation plan contained an unknown action")
		}
	}
	return nil
}

func instanceName(region string, now time.Time, sequence int) string {
	var builder strings.Builder
	lastWasSeparator := false
	for _, char := range region {
		valid := char >= 'a' && char <= 'z' || char >= 'A' && char <= 'Z' || char >= '0' && char <= '9' || char == '-'
		if valid {
			builder.WriteRune(char)
			lastWasSeparator = char == '-'
		} else if !lastWasSeparator {
			builder.WriteByte('-')
			lastWasSeparator = true
		}
	}
	part := strings.Trim(builder.String(), "-")
	if part == "" {
		part = "region"
	}
	return fmt.Sprintf("xray-node-%s-%s-%d", part, now.UTC().Format("20060102150405"), sequence)
}

func operationError(operation, region string) error {
	return fmt.Errorf("Lightsail %s failed in %s", operation, region)
}
