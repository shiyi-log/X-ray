// Package awswrite contains explicit Lightsail instance lifecycle calls.
package awswrite

import (
	"context"
	"errors"
	"net/netip"
	"os"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	awsprofile "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/feature/ec2/imds"
	"github.com/aws/aws-sdk-go-v2/service/lightsail"
	lightsailtypes "github.com/aws/aws-sdk-go-v2/service/lightsail/types"
	"github.com/aws/aws-sdk-go-v2/service/sts"
	lightsailconfig "github.com/mhsanaei/3x-ui/v3/internal/lightsail"
)

const (
	ManagedByTag   = lightsailconfig.ManagedByTag
	ManagedByValue = lightsailconfig.ManagedByValue
	ProjectTag     = lightsailconfig.ProjectTag
	ProjectValue   = lightsailconfig.ProjectValue
	AccountIDTag   = lightsailconfig.AccountIDTag
	ProfileNameTag = lightsailconfig.ProfileNameTag
)

var (
	regionPattern = regexp.MustCompile(`^[a-z]{2}(-gov)?-[a-z]+-[0-9]+$`)
	namePattern   = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9-]{0,61}[A-Za-z0-9]$`)
)

type Owner struct {
	AccountID   string
	ProfileName string
}

type Instance struct {
	Name       string
	Region     string
	State      string
	CreatedAt  time.Time
	PublicIPv4 netip.Addr
	Tags       map[string]string
}

type CreateSpec struct {
	Region           string
	AvailabilityZone string
	Name             string
	BundleID         string
	BlueprintID      string
	AccountID        string
	ProfileName      string
	Tags             map[string]string
}

type CreateRequest struct {
	AvailabilityZone string
	Name             string
	BundleID         string
	BlueprintID      string
	Tags             map[string]string
}

// API is narrow so lifecycle policy can be tested without credentials or AWS.
type API interface {
	CallerIdentity(context.Context) (string, error)
	ListInstances(context.Context, string, string) ([]Instance, string, error)
	CreateInstance(context.Context, string, CreateRequest) error
	GetInstance(context.Context, string, string) (Instance, error)
	DeleteInstance(context.Context, string, string) error
	StopInstance(context.Context, string, string) error
	StartInstance(context.Context, string, string) error
}

type Client struct {
	api                    API
	lifecycleWritesEnabled bool
}

func New(api API) *Client { return &Client{api: api} }

// NewFromProfile binds all calls to one named AWS profile and disables IMDS.
// It never accepts credentials from environment variables.
func NewFromProfile(ctx context.Context, profileName string) (*Client, error) {
	profileName = strings.TrimSpace(profileName)
	if err := lightsailconfig.ValidateProfileName(profileName); err != nil {
		return nil, err
	}
	if err := validateCredentialEnvironment(os.LookupEnv); err != nil {
		return nil, err
	}
	cfg, err := awsprofile.LoadDefaultConfig(ctx,
		awsprofile.WithSharedConfigProfile(profileName),
		awsprofile.WithRegion("us-east-1"),
		awsprofile.WithEC2IMDSClientEnableState(imds.ClientDisabled),
	)
	if err != nil {
		return nil, errors.New("AWS named profile could not be loaded")
	}
	return New(&sdkAPI{config: cfg}), nil
}

func validateCredentialEnvironment(lookup func(string) (string, bool)) error {
	for _, name := range []string{
		"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN",
		"AWS_WEB_IDENTITY_TOKEN_FILE", "AWS_ROLE_ARN", "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
		"AWS_CONTAINER_CREDENTIALS_FULL_URI", "AWS_CONTAINER_AUTHORIZATION_TOKEN",
		"AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE",
	} {
		if value, exists := lookup(name); exists && value != "" {
			return errors.New("credential override environment is not allowed with an AWS named profile")
		}
	}
	return nil
}

func (c *Client) ListInstances(ctx context.Context, region string) ([]Instance, error) {
	if err := c.validate(region); err != nil {
		return nil, err
	}
	var instances []Instance
	token := ""
	seenTokens := map[string]struct{}{}
	for {
		page, next, err := c.api.ListInstances(ctx, region, token)
		if err != nil {
			return nil, errors.New("Lightsail instances could not be listed")
		}
		for _, instance := range page {
			if instance.Name == "" || (instance.Region != "" && instance.Region != region) {
				return nil, errors.New("Lightsail instance inventory contained invalid data")
			}
			if instance.CreatedAt.IsZero() {
				return nil, errors.New("Lightsail instance creation time is missing")
			}
			if instance.Region == "" {
				instance.Region = region
			}
			instances = append(instances, instance)
		}
		if next == "" {
			break
		}
		if _, exists := seenTokens[next]; exists {
			return nil, errors.New("Lightsail instance pagination was invalid")
		}
		seenTokens[next] = struct{}{}
		token = next
	}
	sort.Slice(instances, func(i, j int) bool {
		if instances[i].CreatedAt.Equal(instances[j].CreatedAt) {
			return instances[i].Name < instances[j].Name
		}
		return instances[i].CreatedAt.Before(instances[j].CreatedAt)
	})
	return instances, nil
}

func (c *Client) CreateInstance(ctx context.Context, spec CreateSpec) error {
	if err := c.requireLifecycleWritesEnabled(); err != nil {
		return err
	}
	if err := c.validate(spec.Region); err != nil {
		return err
	}
	if !namePattern.MatchString(spec.Name) || strings.TrimSpace(spec.AvailabilityZone) == "" ||
		strings.TrimSpace(spec.BundleID) == "" || strings.TrimSpace(spec.BlueprintID) == "" ||
		!validAccountID(spec.AccountID) || lightsailconfig.ValidateProfileName(spec.ProfileName) != nil {
		return errors.New("Lightsail create settings are invalid")
	}
	if err := c.verifyAccount(ctx, spec.AccountID); err != nil {
		return err
	}
	tags := make(map[string]string, len(spec.Tags)+4)
	for key, value := range spec.Tags {
		if key == ManagedByTag || key == ProjectTag || key == AccountIDTag || key == ProfileNameTag || key == "" {
			return errors.New("Lightsail ownership tags cannot be overridden")
		}
		tags[key] = value
	}
	tags[ManagedByTag] = ManagedByValue
	tags[ProjectTag] = ProjectValue
	tags[AccountIDTag] = spec.AccountID
	tags[ProfileNameTag] = spec.ProfileName
	if err := c.api.CreateInstance(ctx, spec.Region, CreateRequest{
		AvailabilityZone: spec.AvailabilityZone, Name: spec.Name, BundleID: spec.BundleID, BlueprintID: spec.BlueprintID, Tags: tags,
	}); err != nil {
		return errors.New("Lightsail instance could not be created")
	}
	return nil
}

// DeleteManagedInstance fetches the instance immediately before deletion and
// checks every ownership tag. No force-delete option is exposed.
func (c *Client) DeleteManagedInstance(ctx context.Context, region, name string, owner Owner) error {
	if err := c.requireLifecycleWritesEnabled(); err != nil {
		return err
	}
	if err := c.validate(region); err != nil {
		return err
	}
	if !namePattern.MatchString(name) || !validAccountID(owner.AccountID) || lightsailconfig.ValidateProfileName(owner.ProfileName) != nil {
		return errors.New("Lightsail deletion identity is invalid")
	}
	if err := c.verifyAccount(ctx, owner.AccountID); err != nil {
		return err
	}
	instance, err := c.api.GetInstance(ctx, region, name)
	if err != nil {
		return errors.New("Lightsail instance ownership could not be verified")
	}
	if instance.Name != name || (instance.Region != "" && instance.Region != region) || !ownedBy(instance, owner) {
		return errors.New("Lightsail instance is not owned by this project and profile")
	}
	if err := c.api.DeleteInstance(ctx, region, name); err != nil {
		return errors.New("Lightsail instance could not be deleted")
	}
	return nil
}

func ownedBy(instance Instance, owner Owner) bool {
	return instance.Tags[ManagedByTag] == ManagedByValue && instance.Tags[ProjectTag] == ProjectValue &&
		instance.Tags[AccountIDTag] == owner.AccountID && instance.Tags[ProfileNameTag] == owner.ProfileName
}

func (c *Client) GetInstance(ctx context.Context, region, name string) (Instance, error) {
	if err := c.validate(region); err != nil {
		return Instance{}, err
	}
	if !namePattern.MatchString(name) {
		return Instance{}, errors.New("Lightsail instance name is invalid")
	}
	instance, err := c.api.GetInstance(ctx, region, name)
	if err != nil {
		return Instance{}, errors.New("Lightsail instance could not be read")
	}
	if instance.Name != name || (instance.Region != "" && instance.Region != region) {
		return Instance{}, errors.New("Lightsail instance response was invalid")
	}
	instance.Region = region
	return instance, nil
}

func (c *Client) StopManagedInstance(ctx context.Context, region, name string, owner Owner) error {
	if err := c.requireLifecycleWritesEnabled(); err != nil {
		return err
	}
	if err := c.verifyAccount(ctx, owner.AccountID); err != nil {
		return err
	}
	if err := c.verifyOwnership(ctx, region, name, owner); err != nil {
		return err
	}
	if err := c.api.StopInstance(ctx, region, name); err != nil {
		return errors.New("Lightsail instance could not be stopped")
	}
	return nil
}

func (c *Client) StartManagedInstance(ctx context.Context, region, name string, owner Owner) error {
	if err := c.requireLifecycleWritesEnabled(); err != nil {
		return err
	}
	if err := c.verifyAccount(ctx, owner.AccountID); err != nil {
		return err
	}
	if err := c.verifyOwnership(ctx, region, name, owner); err != nil {
		return err
	}
	if err := c.api.StartInstance(ctx, region, name); err != nil {
		return errors.New("Lightsail instance could not be started")
	}
	return nil
}

func (c *Client) VerifyAccount(ctx context.Context, accountID string) error {
	if !validAccountID(accountID) {
		return errors.New("Lightsail account ID is invalid")
	}
	return c.verifyAccount(ctx, accountID)
}

func (c *Client) verifyAccount(ctx context.Context, expected string) error {
	if c == nil || c.api == nil {
		return errors.New("Lightsail write client is unavailable")
	}
	actual, err := c.api.CallerIdentity(ctx)
	if err != nil || !validAccountID(actual) {
		return errors.New("AWS profile identity could not be verified")
	}
	if actual != expected {
		return errors.New("AWS profile account does not match the configured account")
	}
	return nil
}

func (c *Client) requireLifecycleWritesEnabled() error {
	if c == nil || !c.lifecycleWritesEnabled {
		return errors.New("Lightsail lifecycle writes are disabled")
	}
	return nil
}

func (c *Client) verifyOwnership(ctx context.Context, region, name string, owner Owner) error {
	if err := c.validate(region); err != nil {
		return err
	}
	if !namePattern.MatchString(name) || !validAccountID(owner.AccountID) || lightsailconfig.ValidateProfileName(owner.ProfileName) != nil {
		return errors.New("Lightsail lifecycle identity is invalid")
	}
	instance, err := c.api.GetInstance(ctx, region, name)
	if err != nil {
		return errors.New("Lightsail instance ownership could not be verified")
	}
	if instance.Name != name || (instance.Region != "" && instance.Region != region) || !ownedBy(instance, owner) {
		return errors.New("Lightsail instance is not owned by this project and profile")
	}
	return nil
}

func (c *Client) validate(region string) error {
	if c == nil || c.api == nil {
		return errors.New("Lightsail write client is unavailable")
	}
	if !regionPattern.MatchString(strings.TrimSpace(region)) {
		return errors.New("Lightsail region is invalid")
	}
	return nil
}

func validAccountID(value string) bool {
	return len(value) == 12 && strings.Trim(value, "0123456789") == ""
}

type sdkAPI struct{ config aws.Config }

func (s *sdkAPI) ListInstances(ctx context.Context, region, token string) ([]Instance, string, error) {
	var pageToken *string
	if token != "" {
		pageToken = aws.String(token)
	}
	output, err := lightsail.NewFromConfig(s.regionalConfig(region)).GetInstances(ctx, &lightsail.GetInstancesInput{PageToken: pageToken})
	if err != nil || output == nil {
		return nil, "", errors.New("request failed")
	}
	instances := make([]Instance, 0, len(output.Instances))
	for _, value := range output.Instances {
		instances = append(instances, mapInstance(value))
	}
	return instances, stringValue(output.NextPageToken), nil
}

func (s *sdkAPI) CallerIdentity(ctx context.Context) (string, error) {
	output, err := sts.NewFromConfig(s.config).GetCallerIdentity(ctx, &sts.GetCallerIdentityInput{})
	if err != nil || output == nil || output.Account == nil {
		return "", errors.New("identity request failed")
	}
	return *output.Account, nil
}

func (s *sdkAPI) CreateInstance(ctx context.Context, region string, request CreateRequest) error {
	tags := make([]lightsailtypes.Tag, 0, len(request.Tags))
	for key, value := range request.Tags {
		tags = append(tags, lightsailtypes.Tag{Key: aws.String(key), Value: aws.String(value)})
	}
	_, err := lightsail.NewFromConfig(s.regionalConfig(region)).CreateInstances(ctx, &lightsail.CreateInstancesInput{
		AvailabilityZone: aws.String(request.AvailabilityZone), BlueprintId: aws.String(request.BlueprintID), BundleId: aws.String(request.BundleID),
		InstanceNames: []string{request.Name}, IpAddressType: lightsailtypes.IpAddressTypeIpv4, Tags: tags,
	})
	return err
}

func (s *sdkAPI) GetInstance(ctx context.Context, region, name string) (Instance, error) {
	output, err := lightsail.NewFromConfig(s.regionalConfig(region)).GetInstance(ctx, &lightsail.GetInstanceInput{InstanceName: aws.String(name)})
	if err != nil || output == nil || output.Instance == nil {
		return Instance{}, errors.New("request failed")
	}
	return mapInstance(*output.Instance), nil
}

func (s *sdkAPI) DeleteInstance(ctx context.Context, region, name string) error {
	_, err := lightsail.NewFromConfig(s.regionalConfig(region)).DeleteInstance(ctx, &lightsail.DeleteInstanceInput{InstanceName: aws.String(name)})
	return err
}

func (s *sdkAPI) StopInstance(ctx context.Context, region, name string) error {
	_, err := lightsail.NewFromConfig(s.regionalConfig(region)).StopInstance(ctx, &lightsail.StopInstanceInput{InstanceName: aws.String(name)})
	return err
}

func (s *sdkAPI) StartInstance(ctx context.Context, region, name string) error {
	_, err := lightsail.NewFromConfig(s.regionalConfig(region)).StartInstance(ctx, &lightsail.StartInstanceInput{InstanceName: aws.String(name)})
	return err
}

func (s *sdkAPI) regionalConfig(region string) aws.Config {
	cfg := s.config
	cfg.Region = region
	return cfg
}

func mapInstance(value lightsailtypes.Instance) Instance {
	instance := Instance{
		Name: stringValue(value.Name), CreatedAt: timeValue(value.CreatedAt), State: "unknown",
		Tags: make(map[string]string, len(value.Tags)),
	}
	if value.State != nil && value.State.Name != nil {
		instance.State = *value.State.Name
	}
	if value.Location != nil {
		instance.Region = string(value.Location.RegionName)
	}
	if ip := stringValue(value.PublicIpAddress); ip != "" {
		instance.PublicIPv4, _ = netip.ParseAddr(ip)
	}
	for _, tag := range value.Tags {
		if tag.Key != nil {
			instance.Tags[*tag.Key] = stringValue(tag.Value)
		}
	}
	return instance
}

func stringValue(value *string) string {
	if value == nil {
		return ""
	}
	return *value
}
func timeValue(value *time.Time) time.Time {
	if value == nil {
		return time.Time{}
	}
	return *value
}
