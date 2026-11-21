package awsread

import (
	"context"
	"errors"
	"reflect"
	"strings"
	"testing"

	"github.com/aws/aws-sdk-go-v2/aws"
	lightsailtypes "github.com/aws/aws-sdk-go-v2/service/lightsail/types"
)

type fakeAPI struct {
	accountID  string
	regions    []Region
	zones      []string
	bundles    []Bundle
	blueprints []Blueprint
	err        error
	calls      []string
}

func (f *fakeAPI) CallerIdentity(context.Context) (string, error) {
	f.calls = append(f.calls, "identity")
	return f.accountID, f.err
}
func (f *fakeAPI) Regions(context.Context) ([]Region, error) {
	f.calls = append(f.calls, "regions")
	return f.regions, f.err
}
func (f *fakeAPI) AvailabilityZones(context.Context, string) ([]string, error) {
	f.calls = append(f.calls, "zones")
	return f.zones, f.err
}
func (f *fakeAPI) Bundles(context.Context, string) ([]Bundle, error) {
	f.calls = append(f.calls, "bundles")
	return f.bundles, f.err
}
func (f *fakeAPI) Blueprints(context.Context, string) ([]Blueprint, error) {
	f.calls = append(f.calls, "blueprints")
	return f.blueprints, f.err
}

func TestReadOnlyCatalogReturnsSafeIdentityAndRegionalChoices(t *testing.T) {
	fake := &fakeAPI{
		accountID:  "123456789012",
		regions:    []Region{{Name: "ap-southeast-1", DisplayName: "Singapore"}},
		zones:      []string{"ap-southeast-1a", "ap-southeast-1b"},
		bundles:    []Bundle{{ID: "small_3_0", Name: "Small", Price: 12.0, CPUCount: 2, RAMSizeGB: 2, DiskSizeGB: 60, TransferGB: 3000}},
		blueprints: []Blueprint{{ID: "ubuntu_24_04", Name: "Ubuntu 24.04 LTS", Version: "24.04", Platform: "LINUX_UNIX"}},
	}
	client := New(fake)

	identity, err := client.Identity(context.Background())
	if err != nil || identity.AccountID != "123456789012" {
		t.Fatalf("Identity() = %+v, %v", identity, err)
	}
	regions, err := client.Regions(context.Background())
	if err != nil || !reflect.DeepEqual(regions, fake.regions) {
		t.Fatalf("Regions() = %+v, %v", regions, err)
	}
	bundles, err := client.Bundles(context.Background(), "ap-southeast-1")
	if err != nil || !reflect.DeepEqual(bundles, fake.bundles) {
		t.Fatalf("Bundles() = %+v, %v", bundles, err)
	}
	blueprints, err := client.Blueprints(context.Background(), "ap-southeast-1")
	if err != nil || !reflect.DeepEqual(blueprints, fake.blueprints) {
		t.Fatalf("Blueprints() = %+v, %v", blueprints, err)
	}
	zones, err := client.AvailabilityZones(context.Background(), "ap-southeast-1")
	if err != nil || !reflect.DeepEqual(zones, fake.zones) {
		t.Fatalf("AvailabilityZones() = %v, %v", zones, err)
	}
	if !reflect.DeepEqual(fake.calls, []string{"identity", "regions", "bundles", "blueprints", "zones"}) {
		t.Fatalf("API calls = %v", fake.calls)
	}
}

func TestClientSanitizesSDKErrors(t *testing.T) {
	fake := &fakeAPI{err: errors.New("request failed using secret access key AKIAEXAMPLE")}
	client := New(fake)
	checks := []struct {
		name string
		run  func() error
	}{
		{name: "identity", run: func() error { _, err := client.Identity(context.Background()); return err }},
		{name: "regions", run: func() error { _, err := client.Regions(context.Background()); return err }},
		{name: "bundles", run: func() error { _, err := client.Bundles(context.Background(), "us-east-1"); return err }},
		{name: "blueprints", run: func() error { _, err := client.Blueprints(context.Background(), "us-east-1"); return err }},
	}
	for _, check := range checks {
		t.Run(check.name, func(t *testing.T) {
			err := check.run()
			if err == nil || strings.Contains(err.Error(), "AKIAEXAMPLE") {
				t.Fatalf("%s error leaked SDK detail: %v", check.name, err)
			}
		})
	}
}

func TestClientRejectsInvalidIdentityAndRegionBeforeCallingAPI(t *testing.T) {
	fake := &fakeAPI{accountID: "not-an-account-id"}
	client := New(fake)
	if _, err := client.Identity(context.Background()); err == nil {
		t.Fatal("Identity accepted an invalid account ID")
	}
	if _, err := client.Bundles(context.Background(), "invalid region"); err == nil {
		t.Fatal("Bundles accepted an invalid region")
	}
	if _, err := client.Blueprints(context.Background(), "invalid region"); err == nil {
		t.Fatal("Blueprints accepted an invalid region")
	}
	if !reflect.DeepEqual(fake.calls, []string{"identity"}) {
		t.Fatalf("API calls = %v, invalid regions must not call AWS", fake.calls)
	}
}

func TestMapAvailabilityZonesUsesInstanceZones(t *testing.T) {
	region := lightsailtypes.Region{
		AvailabilityZones:                   []lightsailtypes.AvailabilityZone{{ZoneName: aws.String("us-east-1b")}, {ZoneName: aws.String("us-east-1a")}},
		RelationalDatabaseAvailabilityZones: []lightsailtypes.AvailabilityZone{{ZoneName: aws.String("us-east-1c")}},
	}
	want := []string{"us-east-1a", "us-east-1b"}
	if got := mapAvailabilityZones(region); !reflect.DeepEqual(got, want) {
		t.Fatalf("mapAvailabilityZones() = %v, want %v", got, want)
	}
}

func TestAvailabilityZonesFailsClosedOnEmptyOrMalformedCatalog(t *testing.T) {
	cases := []struct {
		name  string
		zones []string
	}{
		{name: "empty"},
		{name: "malformed", zones: []string{"us-east-1a-unverified"}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			client := New(&fakeAPI{zones: tc.zones})
			if zones, err := client.AvailabilityZones(context.Background(), "us-east-1"); err == nil {
				t.Fatalf("AvailabilityZones() = %v, want a catalog error", zones)
			}
		})
	}
}
