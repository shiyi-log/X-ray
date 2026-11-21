// Package rolling coordinates sequential Lightsail stop/start recovery checks.
package rolling

import (
	"context"
	"fmt"
	"net/netip"
	"sync"
)

// Node identifies a panel node backed by a Lightsail instance.
type Node struct {
	ID         string
	InstanceID string
	Region     string
}

// Operations contains the effects for one node. UpdateNodeAPIAddress must
// update only the API address; caller-owned host, domain, and SNI stay intact.
type Operations interface {
	Stop(context.Context, string, string) error
	Start(context.Context, string, string) error
	WaitUntilRunning(context.Context, string, string) error
	ReadDynamicIPv4(context.Context, string, string) (netip.Addr, error)
	UpdateNodeAPIAddress(context.Context, string, netip.Addr) error
	CheckNodeHealth(context.Context, string) error
	CheckXrayHealth(context.Context, string) error
}

// Runner serializes an entire roll and stops at the first incomplete recovery.
type Runner struct {
	ops Operations
	mu  sync.Mutex
}

func NewRunner(ops Operations) *Runner {
	return &Runner{ops: ops}
}

func (r *Runner) Run(ctx context.Context, nodes []Node) error {
	if r == nil || r.ops == nil {
		return fmt.Errorf("Lightsail restart operations are unavailable")
	}
	r.mu.Lock()
	defer r.mu.Unlock()

	for _, node := range nodes {
		if node.ID == "" || node.InstanceID == "" || node.Region == "" {
			return fmt.Errorf("Lightsail restart node identity is incomplete")
		}
		if err := ctx.Err(); err != nil {
			return err
		}
		if err := r.ops.Stop(ctx, node.Region, node.InstanceID); err != nil {
			return operationError("stop Lightsail instance", node.ID)
		}
		if err := r.ops.Start(ctx, node.Region, node.InstanceID); err != nil {
			return operationError("start Lightsail instance", node.ID)
		}
		if err := r.ops.WaitUntilRunning(ctx, node.Region, node.InstanceID); err != nil {
			return operationError("wait for Lightsail node to run", node.ID)
		}
		address, err := r.ops.ReadDynamicIPv4(ctx, node.Region, node.InstanceID)
		if err != nil {
			return operationError("read dynamic IPv4", node.ID)
		}
		if !address.IsValid() || !address.Is4() || address.IsUnspecified() {
			return fmt.Errorf("Lightsail node %s has no valid dynamic IPv4 address", node.ID)
		}
		if err := r.ops.UpdateNodeAPIAddress(ctx, node.ID, address); err != nil {
			return operationError("update API address", node.ID)
		}
		if err := r.ops.CheckNodeHealth(ctx, node.ID); err != nil {
			return operationError("node health check", node.ID)
		}
		if err := r.ops.CheckXrayHealth(ctx, node.ID); err != nil {
			return operationError("Xray health check", node.ID)
		}
	}
	return nil
}

func operationError(operation, nodeID string) error {
	return fmt.Errorf("%s failed for node %s", operation, nodeID)
}
