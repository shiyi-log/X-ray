package reconcile

import (
	"context"
	"errors"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/mhsanaei/3x-ui/v3/internal/lightsail/awswrite"
	"github.com/mhsanaei/3x-ui/v3/internal/lightsail/plan"
)

type fakeOperations struct {
	instancesByRegion map[string][]awswrite.Instance
	listedRegions     []string
	created           []awswrite.CreateSpec
	deleted           []string
	createErrAt       int
	deleteErrAt       int
	err               error
}

func (f *fakeOperations) ListInstances(_ context.Context, region string) ([]awswrite.Instance, error) {
	f.listedRegions = append(f.listedRegions, region)
	return f.instancesByRegion[region], nil
}

func (f *fakeOperations) CreateInstance(_ context.Context, request awswrite.CreateSpec) error {
	f.created = append(f.created, request)
	if f.createErrAt > 0 && len(f.created) == f.createErrAt {
		return f.err
	}
	return nil
}

func (f *fakeOperations) DeleteManagedInstance(_ context.Context, _, name string, _ awswrite.Owner) error {
	f.deleted = append(f.deleted, name)
	if f.deleteErrAt > 0 && len(f.deleted) == f.deleteErrAt {
		return f.err
	}
	return nil
}

func TestRunCreatesOnlyRegionalDeficitWithDeterministicNames(t *testing.T) {
	fake := &fakeOperations{instancesByRegion: map[string][]awswrite.Instance{
		"ap-southeast-1": {owned("existing", "ap-southeast-1", 1)},
		"us-east-1":      nil,
	}}
	runner := NewRunner(fake)
	err := runner.Run(context.Background(), RunOptions{
		Config: plan.Config{AccountID: "123456789012", ProfileName: "prod", Regions: []plan.RegionTarget{
			{Region: "us-east-1", AvailabilityZone: "us-east-1b", BundleID: "small_3_0", BlueprintID: "ubuntu_24_04", TargetCount: 2},
			{Region: "ap-southeast-1", AvailabilityZone: "ap-southeast-1a", BundleID: "small_3_0", BlueprintID: "ubuntu_24_04", TargetCount: 2},
		}},
		AvailabilityZoneByRegion: map[string]string{"us-east-1": "us-east-1a", "ap-southeast-1": "ap-southeast-1a"},
		Now:                      func() time.Time { return time.Date(2026, 11, 19, 1, 2, 3, 0, time.UTC) },
	})
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(fake.listedRegions, []string{"ap-southeast-1", "us-east-1"}) {
		t.Fatalf("listed regions = %#v", fake.listedRegions)
	}
	if len(fake.created) != 3 {
		t.Fatalf("create calls = %#v", fake.created)
	}
	wantNames := []string{"xray-node-ap-southeast-1-20261119010203-2", "xray-node-us-east-1-20261119010203-1", "xray-node-us-east-1-20261119010203-2"}
	for i, request := range fake.created {
		if request.Name != wantNames[i] || request.AccountID != "123456789012" || request.ProfileName != "prod" {
			t.Fatalf("create request %d = %#v", i, request)
		}
	}
	if fake.created[0].AvailabilityZone != "ap-southeast-1a" || fake.created[1].AvailabilityZone != "us-east-1b" {
		t.Fatalf("create availability zones = %q, %q", fake.created[0].AvailabilityZone, fake.created[1].AvailabilityZone)
	}
}

func TestRunDeletesNewestOwnedOnlyAndStopsOnFirstFailure(t *testing.T) {
	fake := &fakeOperations{
		instancesByRegion: map[string][]awswrite.Instance{"us-east-1": {
			owned("old", "us-east-1", 1), owned("newest", "us-east-1", 3), owned("middle", "us-east-1", 2),
			manual("manual", "us-east-1", 4),
		}},
		deleteErrAt: 1,
		err:         errors.New("provider secret should not escape"),
	}
	err := NewRunner(fake).Run(context.Background(), RunOptions{Config: plan.Config{
		AccountID: "123456789012", ProfileName: "prod",
		Regions: []plan.RegionTarget{{Region: "us-east-1", BundleID: "small_3_0", BlueprintID: "ubuntu_24_04", TargetCount: 1}},
	}})
	if err == nil || strings.Contains(err.Error(), "provider secret") {
		t.Fatalf("error = %v, deleted = %#v, want sanitized failure", err, fake.deleted)
	}
	if len(fake.deleted) != 1 || fake.deleted[0] != "newest" {
		t.Fatalf("deleted = %#v, want first newest owned instance only", fake.deleted)
	}
}

func TestRunRequiresConfiguredZoneOnlyWhenCreating(t *testing.T) {
	fake := &fakeOperations{}
	err := NewRunner(fake).Run(context.Background(), RunOptions{Config: plan.Config{
		AccountID: "123456789012", ProfileName: "prod",
		Regions: []plan.RegionTarget{{Region: "us-east-1", BundleID: "small_3_0", BlueprintID: "ubuntu_24_04", TargetCount: 1}},
	}})
	if err == nil || len(fake.created) != 0 {
		t.Fatalf("error = %v, created = %#v; want fail closed before create", err, fake.created)
	}
}

func TestRunHonorsCancellationBeforeFirstCloudOperation(t *testing.T) {
	fake := &fakeOperations{}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	err := NewRunner(fake).Run(ctx, RunOptions{
		Config: plan.Config{
			AccountID: "123456789012", ProfileName: "prod",
			Regions: []plan.RegionTarget{{Region: "us-east-1", BundleID: "small_3_0", BlueprintID: "ubuntu_24_04", TargetCount: 1}},
		},
		AvailabilityZoneByRegion: map[string]string{"us-east-1": "us-east-1a"},
	})
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("error = %v, want context canceled", err)
	}
	if len(fake.listedRegions) != 0 || len(fake.created) != 0 || len(fake.deleted) != 0 {
		t.Fatalf("operations ran after cancellation: %#v", fake)
	}
}

func owned(id, region string, created int64) awswrite.Instance {
	return awswrite.Instance{
		Name: id, Region: region, CreatedAt: time.Unix(created, 0),
		Tags: map[string]string{
			awswrite.ManagedByTag: awswrite.ManagedByValue, awswrite.ProjectTag: awswrite.ProjectValue,
			awswrite.AccountIDTag: "123456789012", awswrite.ProfileNameTag: "prod",
		},
	}
}

func manual(id, region string, created int64) awswrite.Instance {
	return awswrite.Instance{Name: id, Region: region, CreatedAt: time.Unix(created, 0)}
}
