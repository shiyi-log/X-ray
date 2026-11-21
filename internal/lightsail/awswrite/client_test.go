package awswrite

import (
	"context"
	"errors"
	"net/netip"
	"reflect"
	"strings"
	"testing"
	"time"
)

type fakeAPI struct {
	accountID        string
	identityCalls    int
	instancesByToken map[string][]Instance
	nextToken        map[string]string
	getInstance      Instance
	getErr           error
	getCalls         int
	listTokens       []string
	created          *CreateRequest
	deleted          []string
	stopped          []string
	started          []string
}

func newLifecycleEnabledClientForTest(api API) *Client {
	return &Client{api: api, lifecycleWritesEnabled: true}
}

func (f *fakeAPI) CallerIdentity(context.Context) (string, error) {
	f.identityCalls++
	return f.accountID, nil
}

func (f *fakeAPI) ListInstances(_ context.Context, _ string, token string) ([]Instance, string, error) {
	f.listTokens = append(f.listTokens, token)
	return f.instancesByToken[token], f.nextToken[token], nil
}

func (f *fakeAPI) CreateInstance(_ context.Context, _ string, request CreateRequest) error {
	copy := request
	f.created = &copy
	return nil
}

func (f *fakeAPI) GetInstance(_ context.Context, _, _ string) (Instance, error) {
	f.getCalls++
	return f.getInstance, f.getErr
}

func (f *fakeAPI) DeleteInstance(_ context.Context, _, name string) error {
	f.deleted = append(f.deleted, name)
	return nil
}

func (f *fakeAPI) StopInstance(_ context.Context, _, name string) error {
	f.stopped = append(f.stopped, name)
	return nil
}

func (f *fakeAPI) StartInstance(_ context.Context, _, name string) error {
	f.started = append(f.started, name)
	return nil
}

func TestLifecycleWritesAreDisabledByDefaultBeforeAnyAPICall(t *testing.T) {
	owner := Owner{AccountID: "123456789012", ProfileName: "xray-prod"}
	tests := []struct {
		name string
		call func(*Client) error
	}{
		{name: "create", call: func(client *Client) error {
			return client.CreateInstance(context.Background(), CreateSpec{
				Region: "us-east-1", AvailabilityZone: "us-east-1a", Name: "xray-node-1", BundleID: "small_3_0", BlueprintID: "ubuntu_24_04",
				AccountID: owner.AccountID, ProfileName: owner.ProfileName,
			})
		}},
		{name: "delete", call: func(client *Client) error {
			return client.DeleteManagedInstance(context.Background(), "us-east-1", "node-a", owner)
		}},
		{name: "stop", call: func(client *Client) error {
			return client.StopManagedInstance(context.Background(), "us-east-1", "node-a", owner)
		}},
		{name: "start", call: func(client *Client) error {
			return client.StartManagedInstance(context.Background(), "us-east-1", "node-a", owner)
		}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			fake := &fakeAPI{
				accountID: "123456789012",
				getInstance: Instance{Name: "node-a", Region: "us-east-1", Tags: map[string]string{
					ManagedByTag: ManagedByValue, ProjectTag: ProjectValue, AccountIDTag: owner.AccountID, ProfileNameTag: owner.ProfileName,
				}},
			}
			err := test.call(New(fake))
			if err == nil || err.Error() != "Lightsail lifecycle writes are disabled" {
				t.Fatalf("error = %v, want lifecycle writes disabled", err)
			}
			if fake.identityCalls != 0 || fake.getCalls != 0 || fake.created != nil || len(fake.deleted) != 0 || len(fake.stopped) != 0 || len(fake.started) != 0 {
				t.Fatalf("disabled write reached API: identities=%d gets=%d created=%v deleted=%v stopped=%v started=%v",
					fake.identityCalls, fake.getCalls, fake.created, fake.deleted, fake.stopped, fake.started)
			}
		})
	}
}

func TestLifecycleWriteGateKeepsReadOnlyOperationsAvailable(t *testing.T) {
	created := time.Date(2026, 11, 19, 1, 0, 0, 0, time.UTC)
	fake := &fakeAPI{
		accountID: "123456789012",
		instancesByToken: map[string][]Instance{
			"": {{Name: "node-a", CreatedAt: created}},
		},
		getInstance: Instance{Name: "node-a", State: "running"},
	}
	client := New(fake)

	instances, err := client.ListInstances(context.Background(), "us-east-1")
	if err != nil || len(instances) != 1 || instances[0].Name != "node-a" {
		t.Fatalf("ListInstances() = %#v, %v", instances, err)
	}
	instance, err := client.GetInstance(context.Background(), "us-east-1", "node-a")
	if err != nil || instance.Name != "node-a" {
		t.Fatalf("GetInstance() = %#v, %v", instance, err)
	}
	if err := client.VerifyAccount(context.Background(), "123456789012"); err != nil {
		t.Fatalf("VerifyAccount() = %v", err)
	}
	if fake.identityCalls != 1 || fake.getCalls != 1 {
		t.Fatalf("read-only calls not made as expected: identity=%d get=%d", fake.identityCalls, fake.getCalls)
	}
}

func TestListInstancesFollowsPagesAndPreservesOwnershipMetadata(t *testing.T) {
	created := time.Date(2026, 11, 19, 1, 0, 0, 0, time.UTC)
	fake := &fakeAPI{
		instancesByToken: map[string][]Instance{
			"":       {{Name: "node-a", CreatedAt: created, State: "running", PublicIPv4: netip.MustParseAddr("203.0.113.10"), Tags: map[string]string{ManagedByTag: ManagedByValue}}},
			"page-2": {{Name: "node-b", CreatedAt: created.Add(time.Hour), State: "stopped"}},
		},
		nextToken: map[string]string{"": "page-2"},
	}
	client := New(fake)
	got, err := client.ListInstances(context.Background(), "us-east-1")
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(fake.listTokens, []string{"", "page-2"}) {
		t.Fatalf("page tokens = %#v", fake.listTokens)
	}
	if len(got) != 2 || got[0].Region != "us-east-1" || got[0].CreatedAt != created || got[0].PublicIPv4.String() != "203.0.113.10" || got[0].Tags[ManagedByTag] != ManagedByValue {
		t.Fatalf("first instance = %#v", got[0])
	}
	if got[1].Region != "us-east-1" || got[1].Name != "node-b" {
		t.Fatalf("second instance = %#v", got[1])
	}
}

func TestListInstancesRejectsRepeatedPageToken(t *testing.T) {
	fake := &fakeAPI{nextToken: map[string]string{"": "loop", "loop": "loop"}}
	_, err := New(fake).ListInstances(context.Background(), "us-east-1")
	if err == nil || !strings.Contains(err.Error(), "pagination") {
		t.Fatalf("error = %v, want sanitized pagination error", err)
	}
}

func TestCreateInstanceAddsImmutableProjectOwnershipTags(t *testing.T) {
	fake := &fakeAPI{accountID: "123456789012"}
	client := newLifecycleEnabledClientForTest(fake)
	err := client.CreateInstance(context.Background(), CreateSpec{
		Region: "us-east-1", AvailabilityZone: "us-east-1a", Name: "xray-node-1", BundleID: "small_3_0", BlueprintID: "ubuntu_24_04",
		AccountID: "123456789012", ProfileName: "xray-prod", Tags: map[string]string{"purpose": "proxy"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if fake.created == nil {
		t.Fatal("create call was not made")
	}
	want := map[string]string{
		ManagedByTag: ManagedByValue, ProjectTag: ProjectValue, AccountIDTag: "123456789012",
		ProfileNameTag: "xray-prod", "purpose": "proxy",
	}
	if !reflect.DeepEqual(fake.created.Tags, want) {
		t.Fatalf("create request = %#v", fake.created)
	}
}

func TestCreateInstanceRejectsCallerOverrideOfOwnershipTags(t *testing.T) {
	fake := &fakeAPI{accountID: "123456789012"}
	err := newLifecycleEnabledClientForTest(fake).CreateInstance(context.Background(), CreateSpec{
		Region: "us-east-1", AvailabilityZone: "us-east-1a", Name: "xray-node-1", BundleID: "small_3_0", BlueprintID: "ubuntu_24_04",
		AccountID: "123456789012", ProfileName: "xray-prod", Tags: map[string]string{ManagedByTag: "someone-else"},
	})
	if err == nil || fake.created != nil {
		t.Fatalf("error = %v, create request = %#v; want reject before API call", err, fake.created)
	}
}

func TestDeleteManagedInstanceRechecksOwnershipBeforeDeleting(t *testing.T) {
	fake := &fakeAPI{accountID: "123456789012", getInstance: Instance{
		Name: "node-a", Region: "us-east-1", Tags: map[string]string{
			ManagedByTag: ManagedByValue, ProjectTag: ProjectValue, AccountIDTag: "123456789012", ProfileNameTag: "xray-prod",
		},
	}}
	client := newLifecycleEnabledClientForTest(fake)
	err := client.DeleteManagedInstance(context.Background(), "us-east-1", "node-a", Owner{AccountID: "123456789012", ProfileName: "xray-prod"})
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(fake.deleted, []string{"node-a"}) {
		t.Fatalf("deleted = %#v", fake.deleted)
	}
}

func TestDeleteManagedInstanceRefusesUnownedInstanceAndHidesProviderError(t *testing.T) {
	t.Run("unowned", func(t *testing.T) {
		fake := &fakeAPI{accountID: "123456789012", getInstance: Instance{Name: "node-a", Region: "us-east-1", Tags: map[string]string{ProjectTag: ProjectValue}}}
		err := newLifecycleEnabledClientForTest(fake).DeleteManagedInstance(context.Background(), "us-east-1", "node-a", Owner{AccountID: "123456789012", ProfileName: "xray-prod"})
		if err == nil || len(fake.deleted) != 0 {
			t.Fatalf("error = %v, deleted = %#v", err, fake.deleted)
		}
	})
	t.Run("provider error", func(t *testing.T) {
		fake := &fakeAPI{accountID: "123456789012", getErr: errors.New("secret token leaked")}
		err := newLifecycleEnabledClientForTest(fake).DeleteManagedInstance(context.Background(), "us-east-1", "node-a", Owner{AccountID: "123456789012", ProfileName: "xray-prod"})
		if err == nil || strings.Contains(err.Error(), "secret token leaked") {
			t.Fatalf("error was not sanitized: %v", err)
		}
	})
}

func TestLifecycleMethodsReturnInstanceStatusAndIPv4OnlyForOwnedInstances(t *testing.T) {
	fake := &fakeAPI{accountID: "123456789012", getInstance: Instance{Name: "node-a", State: "running", PublicIPv4: netip.MustParseAddr("203.0.113.12"), Tags: map[string]string{
		ManagedByTag: ManagedByValue, ProjectTag: ProjectValue, AccountIDTag: "123456789012", ProfileNameTag: "xray-prod",
	}}}
	client := newLifecycleEnabledClientForTest(fake)
	owner := Owner{AccountID: "123456789012", ProfileName: "xray-prod"}
	if err := client.StopManagedInstance(context.Background(), "us-east-1", "node-a", owner); err != nil {
		t.Fatal(err)
	}
	if err := client.StartManagedInstance(context.Background(), "us-east-1", "node-a", owner); err != nil {
		t.Fatal(err)
	}
	got, err := client.GetInstance(context.Background(), "us-east-1", "node-a")
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(fake.stopped, []string{"node-a"}) || !reflect.DeepEqual(fake.started, []string{"node-a"}) {
		t.Fatalf("stop/start calls = %#v / %#v", fake.stopped, fake.started)
	}
	if got.State != "running" || got.PublicIPv4.String() != "203.0.113.12" {
		t.Fatalf("instance = %#v", got)
	}
}

func TestStopAndStartRefuseUnownedInstance(t *testing.T) {
	fake := &fakeAPI{accountID: "123456789012", getInstance: Instance{Name: "node-a", Region: "us-east-1", Tags: map[string]string{ProjectTag: ProjectValue}}}
	client := newLifecycleEnabledClientForTest(fake)
	owner := Owner{AccountID: "123456789012", ProfileName: "xray-prod"}
	if err := client.StopManagedInstance(context.Background(), "us-east-1", "node-a", owner); err == nil {
		t.Fatal("StopManagedInstance accepted an instance without all ownership tags")
	}
	if err := client.StartManagedInstance(context.Background(), "us-east-1", "node-a", owner); err == nil {
		t.Fatal("StartManagedInstance accepted an instance without all ownership tags")
	}
	if len(fake.stopped) != 0 || len(fake.started) != 0 {
		t.Fatalf("unowned instance received actions: stop=%#v start=%#v", fake.stopped, fake.started)
	}
}

func TestLifecycleRefusesConfiguredAccountThatDiffersFromProfileIdentity(t *testing.T) {
	fake := &fakeAPI{accountID: "999999999999"}
	client := newLifecycleEnabledClientForTest(fake)
	err := client.CreateInstance(context.Background(), CreateSpec{
		Region: "us-east-1", AvailabilityZone: "us-east-1a", Name: "xray-node-1", BundleID: "small_3_0", BlueprintID: "ubuntu_24_04",
		AccountID: "123456789012", ProfileName: "xray-prod",
	})
	if err == nil || fake.created != nil {
		t.Fatalf("error = %v, create request = %#v; want account mismatch rejected before API call", err, fake.created)
	}
}

func TestListInstancesRejectsMissingCreationTime(t *testing.T) {
	fake := &fakeAPI{instancesByToken: map[string][]Instance{"": {{Name: "node-a", Region: "us-east-1", State: "running"}}}}
	_, err := New(fake).ListInstances(context.Background(), "us-east-1")
	if err == nil || !strings.Contains(err.Error(), "creation time") {
		t.Fatalf("error = %v, want creation time validation failure", err)
	}
}

func TestVerifyAccountRemainsAvailableWithDefaultClient(t *testing.T) {
	fake := &fakeAPI{accountID: "123456789012"}
	if err := New(fake).VerifyAccount(context.Background(), "123456789012"); err != nil {
		t.Fatalf("VerifyAccount returned %v", err)
	}
	if fake.identityCalls != 1 {
		t.Fatalf("identity calls = %d, want 1", fake.identityCalls)
	}
}

func TestManagedLifecycleRejectsAccountMismatchBeforeInstanceLookupOrMutation(t *testing.T) {
	owner := Owner{AccountID: "123456789012", ProfileName: "xray-prod"}
	tests := []struct {
		name string
		call func(*Client) error
	}{
		{name: "delete", call: func(client *Client) error {
			return client.DeleteManagedInstance(context.Background(), "us-east-1", "node-a", owner)
		}},
		{name: "stop", call: func(client *Client) error {
			return client.StopManagedInstance(context.Background(), "us-east-1", "node-a", owner)
		}},
		{name: "start", call: func(client *Client) error {
			return client.StartManagedInstance(context.Background(), "us-east-1", "node-a", owner)
		}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			fake := &fakeAPI{
				accountID: "999999999999",
				getInstance: Instance{Name: "node-a", Region: "us-east-1", Tags: map[string]string{
					ManagedByTag: ManagedByValue, ProjectTag: ProjectValue, AccountIDTag: owner.AccountID, ProfileNameTag: owner.ProfileName,
				}},
			}
			err := test.call(newLifecycleEnabledClientForTest(fake))
			if err == nil {
				t.Fatal("operation accepted an AWS profile for a different account")
			}
			if fake.getCalls != 0 || len(fake.deleted) != 0 || len(fake.stopped) != 0 || len(fake.started) != 0 {
				t.Fatalf("account mismatch reached instance API: gets=%d deletes=%v stops=%v starts=%v", fake.getCalls, fake.deleted, fake.stopped, fake.started)
			}
		})
	}
}
