package lightsail

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"regexp"
	"strings"
)

var (
	regionPattern  = regexp.MustCompile(`^[a-z]{2}(-gov)?-[a-z]+-[0-9]+$`)
	profilePattern = regexp.MustCompile(`^[A-Za-z0-9_+=,.@-]{1,64}$`)
)

const (
	ManagedByTag   = "xray-managed-by"
	ManagedByValue = "xray-node-pool"
	ProjectTag     = "xray-project"
	ProjectValue   = "shiyi-log/X-ray"
	AccountIDTag   = "xray-account-id"
	ProfileNameTag = "xray-aws-profile"
)

type RegionTarget struct {
	Region           string `json:"region"`
	AvailabilityZone string `json:"availabilityZone"`
	BundleID         string `json:"bundleId"`
	BlueprintID      string `json:"blueprintId"`
	TargetCount      int    `json:"targetCount"`
}

func ValidateProfileName(value string) error {
	value = strings.TrimSpace(value)
	if value == "" {
		return errors.New("AWS named profile is required when region targets are configured")
	}
	if !profilePattern.MatchString(value) || strings.HasPrefix(value, "AKIA") || strings.HasPrefix(value, "ASIA") {
		return errors.New("AWS profile name must be a named profile, not a credential")
	}
	return nil
}

func ParseRegionTargets(value string) ([]RegionTarget, error) {
	if strings.TrimSpace(value) == "" || strings.TrimSpace(value) == "[]" {
		return nil, nil
	}
	var targets []RegionTarget
	decoder := json.NewDecoder(strings.NewReader(value))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&targets); err != nil {
		return nil, fmt.Errorf("AWS region targets must be valid JSON: %w", err)
	}
	if err := decoder.Decode(new(any)); err != io.EOF {
		return nil, errors.New("AWS region targets must contain exactly one JSON value")
	}
	seen := make(map[string]struct{}, len(targets))
	for index, target := range targets {
		target.Region = strings.TrimSpace(target.Region)
		target.BundleID = strings.TrimSpace(target.BundleID)
		target.BlueprintID = strings.TrimSpace(target.BlueprintID)
		target.AvailabilityZone = strings.TrimSpace(target.AvailabilityZone)
		if !regionPattern.MatchString(target.Region) {
			return nil, fmt.Errorf("AWS region target %d has an invalid region", index+1)
		}
		if _, ok := seen[target.Region]; ok {
			return nil, fmt.Errorf("AWS region target %d duplicates region %s", index+1, target.Region)
		}
		seen[target.Region] = struct{}{}
		if target.AvailabilityZone != "" && !validAvailabilityZone(target.Region, target.AvailabilityZone) {
			return nil, fmt.Errorf("AWS region target %d has an invalid availability zone", index+1)
		}
		if target.BundleID == "" || len(target.BundleID) > 128 || target.BlueprintID == "" || len(target.BlueprintID) > 128 {
			return nil, fmt.Errorf("AWS region target %d requires a valid Lightsail bundle and blueprint", index+1)
		}
		if target.TargetCount < 0 || target.TargetCount > 1000 {
			return nil, fmt.Errorf("AWS region target %d count must be between 0 and 1000", index+1)
		}
	}
	return targets, nil
}

func validAvailabilityZone(region, zone string) bool {
	return len(zone) == len(region)+1 && strings.HasPrefix(zone, region) && zone[len(region)] >= 'a' && zone[len(region)] <= 'f'
}

func CanonicalRegionTargets(value string) (string, error) {
	targets, err := ParseRegionTargets(value)
	if err != nil {
		return "", err
	}
	if len(targets) == 0 {
		return "[]", nil
	}
	encoded, err := json.Marshal(targets)
	if err != nil {
		return "", fmt.Errorf("encode Lightsail region targets: %w", err)
	}
	return string(encoded), nil
}

func ValidateRegion(value string) error {
	if !regionPattern.MatchString(strings.TrimSpace(value)) {
		return errors.New("AWS region is invalid")
	}
	return nil
}
