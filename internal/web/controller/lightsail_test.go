package controller

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/mhsanaei/3x-ui/v3/internal/database/dbtest"
	"github.com/mhsanaei/3x-ui/v3/internal/lightsail/awsread"
	"github.com/mhsanaei/3x-ui/v3/internal/web/service"
)

type fakeLightsailReader struct {
	identity awsread.Identity
	regions  []awsread.Region
	zones    []string
	bundles  []awsread.Bundle
	images   []awsread.Blueprint
	err      error
}

func (f *fakeLightsailReader) Identity(context.Context) (awsread.Identity, error) {
	return f.identity, f.err
}
func (f *fakeLightsailReader) Regions(context.Context) ([]awsread.Region, error) {
	return f.regions, f.err
}
func (f *fakeLightsailReader) AvailabilityZones(context.Context, string) ([]string, error) {
	return f.zones, f.err
}
func (f *fakeLightsailReader) Bundles(context.Context, string) ([]awsread.Bundle, error) {
	return f.bundles, f.err
}
func (f *fakeLightsailReader) Blueprints(context.Context, string) ([]awsread.Blueprint, error) {
	return f.images, f.err
}

func TestLightsailReadRoutesUseSavedNamedProfileAndSanitizeErrors(t *testing.T) {
	t.Setenv("XUI_DB_FOLDER", t.TempDir())
	dbtest.InitDB(t, filepath.Join(t.TempDir(), "x-ui.db"))
	settings := service.SettingService{}
	all, err := settings.GetAllSetting()
	if err != nil {
		t.Fatalf("read settings: %v", err)
	}
	all.LightsailProfileName = "panel-node-pool"
	if err := settings.UpdateAllSetting(all, service.SecretClears{}); err != nil {
		t.Fatalf("save profile name: %v", err)
	}

	gin.SetMode(gin.TestMode)
	router := gin.New()
	controller := NewSettingController(router.Group("/panel/api"))
	fake := &fakeLightsailReader{
		identity: awsread.Identity{AccountID: "123456789012"},
		regions:  []awsread.Region{{Name: "ap-southeast-1", DisplayName: "Singapore"}},
		zones:    []string{"ap-southeast-1a", "ap-southeast-1b"},
		bundles:  []awsread.Bundle{{ID: "small_3_0", Name: "Small", Price: 12}},
		images:   []awsread.Blueprint{{ID: "ubuntu_24_04", Name: "Ubuntu 24.04 LTS"}},
	}
	var selectedProfile string
	controller.lightsailReaderFactory = func(_ context.Context, profile string) (lightsailReader, error) {
		selectedProfile = profile
		return fake, nil
	}

	post := func(path, body string) *httptest.ResponseRecorder {
		t.Helper()
		req := httptest.NewRequest(http.MethodPost, path, strings.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		resp := httptest.NewRecorder()
		router.ServeHTTP(resp, req)
		return resp
	}

	verify := post("/panel/api/setting/lightsail/verifyProfile", "{\"profileName\":\"panel-node-pool\"}")
	if verify.Code != http.StatusOK || !strings.Contains(verify.Body.String(), "123456789012") {
		t.Fatalf("verify response = %d %s", verify.Code, verify.Body.String())
	}
	if selectedProfile != "panel-node-pool" {
		t.Fatalf("selected profile = %q, want the saved named profile", selectedProfile)
	}

	regions := post("/panel/api/setting/lightsail/regions", "{\"profileName\":\"panel-node-pool\"}")
	if regions.Code != http.StatusOK || !strings.Contains(regions.Body.String(), "ap-southeast-1") {
		t.Fatalf("regions response = %d %s", regions.Code, regions.Body.String())
	}
	zones := post("/panel/api/setting/lightsail/zones", "{\"profileName\":\"panel-node-pool\",\"region\":\"ap-southeast-1\"}")
	if zones.Code != http.StatusOK || !strings.Contains(zones.Body.String(), "ap-southeast-1b") {
		t.Fatalf("availability zones response = %d %s", zones.Code, zones.Body.String())
	}
	catalog := post("/panel/api/setting/lightsail/catalog", "{\"profileName\":\"panel-node-pool\",\"region\":\"ap-southeast-1\"}")
	if catalog.Code != http.StatusOK || !strings.Contains(catalog.Body.String(), "small_3_0") || !strings.Contains(catalog.Body.String(), "ubuntu_24_04") {
		t.Fatalf("catalog response = %d %s", catalog.Code, catalog.Body.String())
	}

	fake.err = errors.New("secret-bearing-provider-response")
	failed := post("/panel/api/setting/lightsail/verifyProfile", "{\"profileName\":\"panel-node-pool\"}")
	if failed.Code != http.StatusOK || strings.Contains(failed.Body.String(), "secret-bearing-provider-response") {
		t.Fatalf("provider detail was leaked: %d %s", failed.Code, failed.Body.String())
	}
	var envelope map[string]any
	if err := json.Unmarshal(failed.Body.Bytes(), &envelope); err != nil {
		t.Fatalf("decode sanitized error: %v", err)
	}
	if success, _ := envelope["success"].(bool); success {
		t.Fatal("failed identity lookup was marked successful")
	}
}
