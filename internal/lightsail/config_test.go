package lightsail

import (
	"strings"
	"testing"
)

func TestRegionTargetsValidateOptionalInstanceZone(t *testing.T) {
	valid := `[{"region":"us-east-1","availabilityZone":"us-east-1b","bundleId":"small_3_0","blueprintId":"ubuntu_24_04","targetCount":1}]`
	targets, err := ParseRegionTargets(valid)
	if err != nil {
		t.Fatal(err)
	}
	if len(targets) != 1 || targets[0].AvailabilityZone != "us-east-1b" {
		t.Fatalf("targets = %#v", targets)
	}
	if targets, err := ParseRegionTargets(`[{"region":"us-east-1","availabilityZone":"","bundleId":"small_3_0","blueprintId":"ubuntu_24_04","targetCount":1}]`); err != nil || len(targets) != 1 {
		t.Fatalf("legacy target without an availability zone cannot be edited: %#v, %v", targets, err)
	}
}

func TestRegionTargetsRejectZoneFromAnotherRegion(t *testing.T) {
	_, err := ParseRegionTargets(`[{"region":"us-east-1","availabilityZone":"us-east-2a","bundleId":"small_3_0","blueprintId":"ubuntu_24_04","targetCount":1}]`)
	if err == nil || !strings.Contains(err.Error(), "availability zone") {
		t.Fatalf("error = %v, want wrong-region availability zone rejected", err)
	}
}

func TestRegionTargetsPreserveOptionalAvailabilityZone(t *testing.T) {
	targets, err := ParseRegionTargets(`[{"region":"us-east-1","availabilityZone":"us-east-1b","bundleId":"small_3_0","blueprintId":"ubuntu_24_04","targetCount":1}]`)
	if err != nil || len(targets) != 1 || targets[0].AvailabilityZone != "us-east-1b" {
		t.Fatalf("targets = %#v, err = %v", targets, err)
	}
	canonical, err := CanonicalRegionTargets(`[{"region":"us-east-1","availabilityZone":"us-east-1b","bundleId":"small_3_0","blueprintId":"ubuntu_24_04","targetCount":1}]`)
	if err != nil || !strings.Contains(canonical, `"availabilityZone":"us-east-1b"`) {
		t.Fatalf("canonical = %q, err = %v", canonical, err)
	}
}

func TestZeroTargetDoesNotRequireAvailabilityZone(t *testing.T) {
	targets, err := ParseRegionTargets(`[{"region":"us-east-1","availabilityZone":"","bundleId":"small_3_0","blueprintId":"ubuntu_24_04","targetCount":0}]`)
	if err != nil || len(targets) != 1 {
		t.Fatalf("targets = %#v, err = %v", targets, err)
	}
}
