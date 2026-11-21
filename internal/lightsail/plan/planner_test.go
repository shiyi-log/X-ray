package plan

import (
	"testing"
	"time"
)

func TestPlanCreatesOnlyTheRegionalDeficit(t *testing.T) {
	got, err := Plan(Config{
		AccountID:   "123456789012",
		ProfileName: "production",
		Regions:     []RegionTarget{{Region: "ap-southeast-1", AvailabilityZone: "ap-southeast-1a", BundleID: "small_3_0", BlueprintID: "ubuntu_24_04", TargetCount: 3}},
	}, []Instance{ownedInstance("one", "ap-southeast-1", 1)})
	if err != nil {
		t.Fatalf("Plan returned error: %v", err)
	}
	if len(got) != 2 || got[0].Kind != Create || got[1].Kind != Create {
		t.Fatalf("actions = %+v, want two create actions", got)
	}
	for _, action := range got {
		if action.Region != "ap-southeast-1" || action.BundleID != "small_3_0" || action.BlueprintID != "ubuntu_24_04" {
			t.Fatalf("create action lost target configuration: %+v", action)
		}
		if action.AvailabilityZone != "ap-southeast-1a" {
			t.Fatalf("create action availability zone = %q", action.AvailabilityZone)
		}
	}
}

func TestPlanDeletesNewestOwnedInstancesFirstAndLeavesManualInstances(t *testing.T) {
	instances := []Instance{
		ownedInstance("old", "us-east-1", 1),
		ownedInstance("newest", "us-east-1", 3),
		ownedInstance("middle", "us-east-1", 2),
		{ID: "manual", Region: "us-east-1", CreatedAt: time.Unix(4, 0)},
	}
	got, err := Plan(Config{AccountID: "123456789012", ProfileName: "production", Regions: []RegionTarget{{Region: "us-east-1", BundleID: "small_3_0", BlueprintID: "ubuntu_24_04", TargetCount: 1}}}, instances)
	if err != nil {
		t.Fatalf("Plan returned error: %v", err)
	}
	if len(got) != 2 || got[0].InstanceID != "newest" || got[1].InstanceID != "middle" {
		t.Fatalf("delete actions = %+v, want newest then middle", got)
	}
}

func TestPlanTargetZeroDeletesOnlyOwnedInstancesForTheConfiguredAccount(t *testing.T) {
	instances := []Instance{
		ownedInstance("owned", "eu-west-1", 1),
		{ID: "manual", Region: "eu-west-1", CreatedAt: time.Unix(2, 0)},
		{ID: "other-account", Region: "eu-west-1", CreatedAt: time.Unix(3, 0), Tags: map[string]string{ManagedByTag: ManagedByValue, AccountIDTag: "999999999999", ProjectTag: ProjectValue, ProfileNameTag: "production"}},
		{ID: "other-profile", Region: "eu-west-1", CreatedAt: time.Unix(4, 0), Tags: map[string]string{ManagedByTag: ManagedByValue, AccountIDTag: "123456789012", ProjectTag: ProjectValue, ProfileNameTag: "staging"}},
	}
	got, err := Plan(Config{AccountID: "123456789012", ProfileName: "production", Regions: []RegionTarget{{Region: "eu-west-1", TargetCount: 0}}}, instances)
	if err != nil {
		t.Fatalf("Plan returned error: %v", err)
	}
	if len(got) != 1 || got[0].InstanceID != "owned" || got[0].Kind != Delete {
		t.Fatalf("actions = %+v, want only the project-owned instance", got)
	}
}

func TestPlanRejectsInvalidOrDuplicateRegionalTargets(t *testing.T) {
	tests := []struct {
		name   string
		config Config
	}{
		{name: "negative target", config: Config{AccountID: "123456789012", ProfileName: "production", Regions: []RegionTarget{{Region: "us-east-1", TargetCount: -1}}}},
		{name: "duplicate region", config: Config{AccountID: "123456789012", ProfileName: "production", Regions: []RegionTarget{{Region: "us-east-1"}, {Region: "us-east-1"}}}},
		{name: "incomplete create target", config: Config{AccountID: "123456789012", ProfileName: "production", Regions: []RegionTarget{{Region: "us-east-1", TargetCount: 1}}}},
		{name: "wrong-region availability zone", config: Config{AccountID: "123456789012", ProfileName: "production", Regions: []RegionTarget{{Region: "us-east-1", AvailabilityZone: "us-east-2a", BundleID: "small_3_0", BlueprintID: "ubuntu_24_04", TargetCount: 1}}}},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if _, err := Plan(tt.config, nil); err == nil {
				t.Fatal("Plan succeeded, want validation error")
			}
		})
	}
}

func ownedInstance(id, region string, createdSeconds int64) Instance {
	return Instance{
		ID:        id,
		Region:    region,
		CreatedAt: time.Unix(createdSeconds, 0),
		Tags: map[string]string{
			ManagedByTag:   ManagedByValue,
			ProjectTag:     ProjectValue,
			AccountIDTag:   "123456789012",
			ProfileNameTag: "production",
		},
	}
}
