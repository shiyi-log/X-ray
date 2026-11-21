// Package plan computes Lightsail capacity changes without making cloud calls.
package plan

import (
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"
)

const (
	// ManagedByTag and ProjectTag distinguish instances created by this application.
	ManagedByTag   = "xray-managed-by"
	ManagedByValue = "xray-node-pool"
	ProjectTag     = "xray-project"
	ProjectValue   = "shiyi-log/X-ray"
	AccountIDTag   = "xray-account-id"
	ProfileNameTag = "xray-aws-profile"
)

type Config struct {
	AccountID   string
	ProfileName string
	Regions     []RegionTarget
}

type RegionTarget struct {
	Region           string
	AvailabilityZone string
	BundleID         string
	BlueprintID      string
	TargetCount      int
}

type Instance struct {
	ID        string
	Region    string
	CreatedAt time.Time
	Status    string
	Tags      map[string]string
}

type ActionKind string

const (
	Create ActionKind = "create"
	Delete ActionKind = "delete"
)

type Action struct {
	Kind             ActionKind
	Region           string
	AvailabilityZone string
	BundleID         string
	BlueprintID      string
	InstanceID       string
}

// Plan emits only the capacity delta for this project's explicitly tagged
// Lightsail instances. Manual or differently owned instances never contribute
// to regional capacity and are never returned as delete targets.
func Plan(config Config, instances []Instance) ([]Action, error) {
	if strings.TrimSpace(config.AccountID) == "" || strings.TrimSpace(config.ProfileName) == "" {
		return nil, errors.New("Lightsail account and named profile are required")
	}
	targets := make(map[string]RegionTarget, len(config.Regions))
	for _, target := range config.Regions {
		region := strings.TrimSpace(target.Region)
		if region == "" {
			return nil, errors.New("Lightsail region is required")
		}
		if _, exists := targets[region]; exists {
			return nil, fmt.Errorf("duplicate Lightsail region %q", region)
		}
		if target.TargetCount < 0 {
			return nil, fmt.Errorf("Lightsail target count for %q cannot be negative", region)
		}
		target.Region = region
		if target.TargetCount > 0 && (strings.TrimSpace(target.BundleID) == "" || strings.TrimSpace(target.BlueprintID) == "") {
			return nil, fmt.Errorf("Lightsail bundle and blueprint are required for %q", region)
		}
		if target.AvailabilityZone != "" && (len(target.AvailabilityZone) != len(region)+1 || !strings.HasPrefix(target.AvailabilityZone, region) || target.AvailabilityZone[len(region)] < 'a' || target.AvailabilityZone[len(region)] > 'f') {
			return nil, fmt.Errorf("Lightsail availability zone is invalid for %q", region)
		}
		targets[region] = target
	}

	regions := make([]string, 0, len(targets))
	for region := range targets {
		regions = append(regions, region)
	}
	sort.Strings(regions)

	ownedByRegion := make(map[string][]Instance, len(targets))
	for _, instance := range instances {
		if _, configured := targets[instance.Region]; !configured || !ownedByThisProject(instance, config) {
			continue
		}
		if strings.EqualFold(strings.TrimSpace(instance.Status), "terminated") {
			continue
		}
		ownedByRegion[instance.Region] = append(ownedByRegion[instance.Region], instance)
	}

	actions := make([]Action, 0)
	for _, region := range regions {
		target := targets[region]
		owned := ownedByRegion[region]
		if len(owned) > target.TargetCount {
			sort.Slice(owned, func(i, j int) bool {
				if owned[i].CreatedAt.Equal(owned[j].CreatedAt) {
					return owned[i].ID > owned[j].ID
				}
				return owned[i].CreatedAt.After(owned[j].CreatedAt)
			})
			for _, instance := range owned[:len(owned)-target.TargetCount] {
				actions = append(actions, Action{Kind: Delete, Region: region, InstanceID: instance.ID})
			}
			continue
		}
		for range target.TargetCount - len(owned) {
			actions = append(actions, Action{
				Kind:        Create,
				Region:      region,
				AvailabilityZone: target.AvailabilityZone,
				BundleID:    target.BundleID,
				BlueprintID: target.BlueprintID,
			})
		}
	}
	return actions, nil
}

func ownedByThisProject(instance Instance, config Config) bool {
	return instance.ID != "" &&
		instance.Tags[ManagedByTag] == ManagedByValue &&
		instance.Tags[ProjectTag] == ProjectValue &&
		instance.Tags[AccountIDTag] == config.AccountID &&
		instance.Tags[ProfileNameTag] == config.ProfileName
}
