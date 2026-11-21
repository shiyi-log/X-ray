package rolling

import (
	"context"
	"errors"
	"net/netip"
	"reflect"
	"strings"
	"testing"
)

func TestRunStopsAndChecksEachNodeBeforeAdvancing(t *testing.T) {
	ops := &recordingOperations{ips: map[string]string{"instance-1": "203.0.113.10", "instance-2": "203.0.113.11"}}
	runner := NewRunner(ops)
	nodes := []Node{{ID: "node-1", InstanceID: "instance-1", Region: "us-east-1"}, {ID: "node-2", InstanceID: "instance-2", Region: "us-east-1"}}

	if err := runner.Run(context.Background(), nodes); err != nil {
		t.Fatalf("Run returned error: %v", err)
	}

	want := []string{
		"stop:instance-1", "start:instance-1", "wait-running:instance-1", "read-ip:instance-1",
		"update-api:node-1:203.0.113.10", "node-health:node-1", "xray-health:node-1",
		"stop:instance-2", "start:instance-2", "wait-running:instance-2", "read-ip:instance-2",
		"update-api:node-2:203.0.113.11", "node-health:node-2", "xray-health:node-2",
	}
	if !reflect.DeepEqual(ops.calls, want) {
		t.Fatalf("calls = %#v, want %#v", ops.calls, want)
	}
}

func TestRunStopsTheRollWhenAnyStepFails(t *testing.T) {
	steps := []string{
		"stop:instance-1", "start:instance-1", "wait-running:instance-1", "read-ip:instance-1",
		"update-api:node-1:203.0.113.10", "node-health:node-1", "xray-health:node-1",
	}
	for _, failedStep := range steps {
		t.Run(failedStep, func(t *testing.T) {
			ops := &recordingOperations{ips: map[string]string{"instance-1": "203.0.113.10", "instance-2": "203.0.113.11"}, failAt: failedStep}
			runner := NewRunner(ops)
			nodes := []Node{{ID: "node-1", InstanceID: "instance-1", Region: "us-east-1"}, {ID: "node-2", InstanceID: "instance-2", Region: "us-east-1"}}

			err := runner.Run(context.Background(), nodes)
			if err == nil {
				t.Fatal("Run succeeded, want failed step to stop the roll")
			}
			for _, call := range ops.calls {
				if call == "stop:instance-2" {
					t.Fatalf("started processing the next node after %q failed: %#v", failedStep, ops.calls)
				}
			}
		})
	}
}

func TestRunRejectsMissingOrNonIPv4AddressBeforeUpdatingNode(t *testing.T) {
	for _, ip := range []string{"", "2001:db8::1"} {
		t.Run(ip, func(t *testing.T) {
			ops := &recordingOperations{ips: map[string]string{"node-1": ip}}
			err := NewRunner(ops).Run(context.Background(), []Node{{ID: "node-1", InstanceID: "instance-1", Region: "us-east-1"}})
			if err == nil {
				t.Fatal("Run succeeded, want an address error")
			}
			for _, call := range ops.calls {
				if len(call) >= len("update-api:") && call[:len("update-api:")] == "update-api:" {
					t.Fatalf("updated node API address with invalid IPv4 %q: %#v", ip, ops.calls)
				}
			}
		})
	}
}

func TestRunDoesNotExposeUnderlyingOperationErrorText(t *testing.T) {
	ops := &recordingOperations{ips: map[string]string{"instance-1": "203.0.113.10"}, failAt: "stop:instance-1", failure: errors.New("secret-bearing-provider-details")}
	err := NewRunner(ops).Run(context.Background(), []Node{{ID: "node-1", InstanceID: "instance-1", Region: "us-east-1"}})
	if err == nil {
		t.Fatal("Run succeeded, want stop error")
	}
	if strings.Contains(err.Error(), "secret-bearing-provider-details") {
		t.Fatalf("Run exposed operation details: %v", err)
	}
}

type recordingOperations struct {
	calls   []string
	ips     map[string]string
	failAt  string
	failure error
}

func (o *recordingOperations) record(call string) error {
	o.calls = append(o.calls, call)
	if call == o.failAt {
		if o.failure != nil {
			return o.failure
		}
		return errors.New("operation failed")
	}
	return nil
}

func (o *recordingOperations) Stop(_ context.Context, _ string, instanceID string) error {
	return o.record("stop:" + instanceID)
}

func (o *recordingOperations) Start(_ context.Context, _ string, instanceID string) error {
	return o.record("start:" + instanceID)
}

func (o *recordingOperations) WaitUntilRunning(_ context.Context, _ string, instanceID string) error {
	return o.record("wait-running:" + instanceID)
}

func (o *recordingOperations) ReadDynamicIPv4(_ context.Context, _ string, instanceID string) (netip.Addr, error) {
	call := "read-ip:" + instanceID
	if err := o.record(call); err != nil {
		return netip.Addr{}, err
	}
	ip, err := netip.ParseAddr(o.ips[instanceID])
	return ip, err
}

func (o *recordingOperations) UpdateNodeAPIAddress(_ context.Context, nodeID string, address netip.Addr) error {
	return o.record("update-api:" + nodeID + ":" + address.String())
}

func (o *recordingOperations) CheckNodeHealth(_ context.Context, nodeID string) error {
	return o.record("node-health:" + nodeID)
}

func (o *recordingOperations) CheckXrayHealth(_ context.Context, nodeID string) error {
	return o.record("xray-health:" + nodeID)
}
