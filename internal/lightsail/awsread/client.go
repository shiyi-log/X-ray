// Package awsread exposes a small read-only view of the AWS Lightsail catalog.
package awsread

import (
	"context"
	"errors"
	"os"
	"regexp"
	"sort"
	"strings"

	"github.com/aws/aws-sdk-go-v2/aws"
	awsprofile "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/feature/ec2/imds"
	"github.com/aws/aws-sdk-go-v2/service/lightsail"
	lightsailtypes "github.com/aws/aws-sdk-go-v2/service/lightsail/types"
	"github.com/aws/aws-sdk-go-v2/service/sts"
	lightsailconfig "github.com/mhsanaei/3x-ui/v3/internal/lightsail"
)

var regionNamePattern = regexp.MustCompile(`^[a-z]{2}(-gov)?-[a-z]+-[0-9]+$`)

// API deliberately contains read operations only. Lifecycle writes live in a
// separate package and are not available through this client.
type API interface {
	CallerIdentity(context.Context) (string, error)
	Regions(context.Context) ([]Region, error)
	AvailabilityZones(context.Context, string) ([]string, error)
	Bundles(context.Context, string) ([]Bundle, error)
	Blueprints(context.Context, string) ([]Blueprint, error)
}

type Client struct {
	api API
}

type Identity struct {
	AccountID string `json:"accountId"`
}

type Region struct {
	Name        string `json:"name"`
	DisplayName string `json:"displayName"`
}

type Bundle struct {
	ID         string  `json:"id"`
	Name       string  `json:"name"`
	Price      float64 `json:"price"`
	CPUCount   int32   `json:"cpuCount"`
	RAMSizeGB  float64 `json:"ramSizeGb"`
	DiskSizeGB int32   `json:"diskSizeGb"`
	TransferGB int32   `json:"transferGb"`
	Active     bool    `json:"active"`
}

type Blueprint struct {
	ID           string `json:"id"`
	Name         string `json:"name"`
	Version      string `json:"version"`
	Platform     string `json:"platform"`
	Type         string `json:"type"`
	MinimumPower int32  `json:"minimumPower"`
	Active       bool   `json:"active"`
}

func New(api API) *Client {
	return &Client{api: api}
}

// NewFromProfile loads only the selected named AWS profile. It does not read
// credentials until an API method is invoked. The returned client cannot make
// Lightsail lifecycle changes.
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
		"AWS_ACCESS_KEY_ID",
		"AWS_SECRET_ACCESS_KEY",
		"AWS_SESSION_TOKEN",
		"AWS_SECURITY_TOKEN",
		"AWS_WEB_IDENTITY_TOKEN_FILE",
		"AWS_ROLE_ARN",
		"AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
		"AWS_CONTAINER_CREDENTIALS_FULL_URI",
		"AWS_CONTAINER_AUTHORIZATION_TOKEN",
		"AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE",
	} {
		if value, exists := lookup(name); exists && value != "" {
			return errors.New("credential override environment is not allowed with an AWS named profile")
		}
	}
	return nil
}

func (c *Client) Identity(ctx context.Context) (Identity, error) {
	if c == nil || c.api == nil {
		return Identity{}, errors.New("AWS read client is unavailable")
	}
	accountID, err := c.api.CallerIdentity(ctx)
	if err != nil {
		return Identity{}, errors.New("AWS identity verification failed")
	}
	if len(accountID) != 12 || strings.Trim(accountID, "0123456789") != "" {
		return Identity{}, errors.New("AWS identity response was invalid")
	}
	return Identity{AccountID: accountID}, nil
}

func (c *Client) Regions(ctx context.Context) ([]Region, error) {
	if c == nil || c.api == nil {
		return nil, errors.New("AWS read client is unavailable")
	}
	regions, err := c.api.Regions(ctx)
	if err != nil {
		return nil, errors.New("Lightsail region catalog could not be read")
	}
	for _, region := range regions {
		if !regionNamePattern.MatchString(region.Name) {
			return nil, errors.New("Lightsail region catalog contained an invalid region")
		}
	}
	sort.Slice(regions, func(i, j int) bool { return regions[i].Name < regions[j].Name })
	return regions, nil
}

func (c *Client) AvailabilityZones(ctx context.Context, region string) ([]string, error) {
	if c == nil || c.api == nil {
		return nil, errors.New("AWS read client is unavailable")
	}
	if !regionNamePattern.MatchString(region) {
		return nil, errors.New("Lightsail region is invalid")
	}
	zones, err := c.api.AvailabilityZones(ctx, region)
	if err != nil {
		return nil, errors.New("Lightsail availability zones could not be read")
	}
	if len(zones) == 0 {
		return nil, errors.New("Lightsail availability zone catalog was empty")
	}
	seen := make(map[string]struct{}, len(zones))
	for _, zone := range zones {
		if len(zone) != len(region)+1 || !strings.HasPrefix(zone, region) || zone[len(region)] < 'a' || zone[len(region)] > 'f' {
			return nil, errors.New("Lightsail availability zone catalog contained an invalid zone")
		}
		if _, exists := seen[zone]; exists {
			return nil, errors.New("Lightsail availability zone catalog contained a duplicate zone")
		}
		seen[zone] = struct{}{}
	}
	sort.Strings(zones)
	return zones, nil
}

func (c *Client) Bundles(ctx context.Context, region string) ([]Bundle, error) {
	if c == nil || c.api == nil {
		return nil, errors.New("AWS read client is unavailable")
	}
	if !regionNamePattern.MatchString(region) {
		return nil, errors.New("Lightsail region is invalid")
	}
	bundles, err := c.api.Bundles(ctx, region)
	if err != nil {
		return nil, errors.New("Lightsail bundle catalog could not be read")
	}
	return bundles, nil
}

func (c *Client) Blueprints(ctx context.Context, region string) ([]Blueprint, error) {
	if c == nil || c.api == nil {
		return nil, errors.New("AWS read client is unavailable")
	}
	if !regionNamePattern.MatchString(region) {
		return nil, errors.New("Lightsail region is invalid")
	}
	blueprints, err := c.api.Blueprints(ctx, region)
	if err != nil {
		return nil, errors.New("Lightsail blueprint catalog could not be read")
	}
	return blueprints, nil
}

type sdkAPI struct {
	config aws.Config
}

func (s *sdkAPI) CallerIdentity(ctx context.Context) (string, error) {
	output, err := sts.NewFromConfig(s.config).GetCallerIdentity(ctx, &sts.GetCallerIdentityInput{})
	if err != nil || output == nil || output.Account == nil {
		return "", errors.New("identity request failed")
	}
	return *output.Account, nil
}

func (s *sdkAPI) Regions(ctx context.Context) ([]Region, error) {
	output, err := lightsail.NewFromConfig(s.config).GetRegions(ctx, &lightsail.GetRegionsInput{})
	if err != nil || output == nil {
		return nil, errors.New("region request failed")
	}
	regions := make([]Region, 0, len(output.Regions))
	for _, value := range output.Regions {
		regions = append(regions, Region{Name: string(value.Name), DisplayName: stringValue(value.DisplayName)})
	}
	return regions, nil
}

func (s *sdkAPI) AvailabilityZones(ctx context.Context, region string) ([]string, error) {
	output, err := lightsail.NewFromConfig(s.regionalConfig(region)).GetRegions(ctx, &lightsail.GetRegionsInput{})
	if err != nil || output == nil {
		return nil, errors.New("availability zone request failed")
	}
	for _, item := range output.Regions {
		if string(item.Name) != region {
			continue
		}
		return mapAvailabilityZones(item), nil
	}
	return nil, errors.New("region was not returned by Lightsail")
}

func mapAvailabilityZones(region lightsailtypes.Region) []string {
	zones := make([]string, 0, len(region.AvailabilityZones))
	for _, zone := range region.AvailabilityZones {
		if zone.ZoneName != nil && *zone.ZoneName != "" {
			zones = append(zones, *zone.ZoneName)
		}
	}
	sort.Strings(zones)
	return zones
}

func (s *sdkAPI) Bundles(ctx context.Context, region string) ([]Bundle, error) {
	api := lightsail.NewFromConfig(s.regionalConfig(region))
	var result []Bundle
	var token *string
	seenTokens := map[string]struct{}{}
	for {
		output, err := api.GetBundles(ctx, &lightsail.GetBundlesInput{PageToken: token})
		if err != nil || output == nil {
			return nil, errors.New("bundle request failed")
		}
		for _, value := range output.Bundles {
			result = append(result, mapBundle(value))
		}
		if output.NextPageToken == nil || *output.NextPageToken == "" {
			break
		}
		if _, exists := seenTokens[*output.NextPageToken]; exists {
			return nil, errors.New("bundle catalog pagination was invalid")
		}
		seenTokens[*output.NextPageToken] = struct{}{}
		token = output.NextPageToken
	}
	return result, nil
}

func (s *sdkAPI) Blueprints(ctx context.Context, region string) ([]Blueprint, error) {
	api := lightsail.NewFromConfig(s.regionalConfig(region))
	var result []Blueprint
	var token *string
	seenTokens := map[string]struct{}{}
	for {
		output, err := api.GetBlueprints(ctx, &lightsail.GetBlueprintsInput{PageToken: token})
		if err != nil || output == nil {
			return nil, errors.New("blueprint request failed")
		}
		for _, value := range output.Blueprints {
			result = append(result, mapBlueprint(value))
		}
		if output.NextPageToken == nil || *output.NextPageToken == "" {
			break
		}
		if _, exists := seenTokens[*output.NextPageToken]; exists {
			return nil, errors.New("blueprint catalog pagination was invalid")
		}
		seenTokens[*output.NextPageToken] = struct{}{}
		token = output.NextPageToken
	}
	return result, nil
}

func (s *sdkAPI) regionalConfig(region string) aws.Config {
	cfg := s.config
	cfg.Region = region
	return cfg
}

func mapBundle(value lightsailtypes.Bundle) Bundle {
	return Bundle{
		ID:         stringValue(value.BundleId),
		Name:       stringValue(value.Name),
		Price:      float64Value(value.Price),
		CPUCount:   int32Value(value.CpuCount),
		RAMSizeGB:  float64Value(value.RamSizeInGb),
		DiskSizeGB: int32Value(value.DiskSizeInGb),
		TransferGB: int32Value(value.TransferPerMonthInGb),
		Active:     boolValue(value.IsActive),
	}
}

func mapBlueprint(value lightsailtypes.Blueprint) Blueprint {
	return Blueprint{
		ID:           stringValue(value.BlueprintId),
		Name:         stringValue(value.Name),
		Version:      stringValue(value.Version),
		Platform:     string(value.Platform),
		Type:         string(value.Type),
		MinimumPower: int32Value(value.MinPower),
		Active:       boolValue(value.IsActive),
	}
}

func stringValue(value *string) string {
	if value == nil {
		return ""
	}
	return *value
}
func int32Value(value *int32) int32 {
	if value == nil {
		return 0
	}
	return *value
}
func float64Value(value *float32) float64 {
	if value == nil {
		return 0
	}
	return float64(*value)
}
func boolValue(value *bool) bool {
	return value != nil && *value
}
