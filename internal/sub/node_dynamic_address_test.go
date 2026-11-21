package sub

import (
	"net/netip"
	"strings"
	"testing"

	"github.com/mhsanaei/3x-ui/v3/internal/database"
	"github.com/mhsanaei/3x-ui/v3/internal/database/model"
	"github.com/mhsanaei/3x-ui/v3/internal/web/service"
)

func TestDynamicNodeAddressRefreshesInheritedSubscriptionAndPreservesHostOverrides(t *testing.T) {
	seedSubDB(t)
	db := database.GetDB()
	node := &model.Node{
		Name:     "lightsail-node",
		Scheme:   "https",
		Address:  "203.0.113.10",
		Port:     2053,
		BasePath: "/panel/",
		Enable:   true,
	}
	if err := db.Create(node).Error; err != nil {
		t.Fatalf("create node: %v", err)
	}

	inherited := seedSubInbound(t, "s1", "inherited", 4431, 1, wsTLSStream)
	hostInbound := seedSubInbound(t, "s1", "hosted", 4432, 2, wsTLSStream)
	for _, inbound := range []*model.Inbound{inherited, hostInbound} {
		if err := db.Model(&model.Inbound{}).Where("id = ?", inbound.Id).Update("node_id", node.Id).Error; err != nil {
			t.Fatalf("attach inbound to node: %v", err)
		}
	}
	seedHost(t, &model.Host{
		InboundId:  hostInbound.Id,
		SortOrder:  1,
		Remark:     "manual endpoint",
		Address:    "manual.example.com",
		Port:       8443,
		Security:   "tls",
		Sni:        "manual.sni.example",
		HostHeader: "manual.host.example",
	})

	getLinks := func() []string {
		t.Helper()
		links, _, _, _, err := NewSubService("").GetSubs("s1", "request.example.com")
		if err != nil {
			t.Fatalf("get subscription: %v", err)
		}
		return links
	}
	manualLink := func(links []string) string {
		t.Helper()
		for _, link := range links {
			if strings.Contains(link, "manual.example.com:8443") {
				return link
			}
		}
		t.Fatal("manual Host endpoint was not rendered")
		return ""
	}

	before := getLinks()
	if !strings.Contains(strings.Join(before, "\n"), "203.0.113.10:4431") {
		t.Fatal("inherited endpoint did not use the current node address")
	}
	beforeManual := manualLink(before)
	if !strings.Contains(beforeManual, "sni=manual.sni.example") || !strings.Contains(beforeManual, "host=manual.host.example") {
		t.Fatal("manual endpoint did not preserve its configured SNI and HostHeader")
	}

	if err := (&service.NodeService{}).UpdateDynamicIPv4(node.Id, netip.MustParseAddr("198.51.100.25")); err != nil {
		t.Fatalf("update dynamic node API address: %v", err)
	}
	after := getLinks()
	joined := strings.Join(after, "\n")
	if !strings.Contains(joined, "198.51.100.25:4431") || strings.Contains(joined, "203.0.113.10:4431") {
		t.Fatal("inherited subscription endpoint did not follow the updated node API address")
	}
	if got := manualLink(after); got != beforeManual {
		t.Fatal("manual Host endpoint changed after the node API address update")
	}
}
