package service

import (
	"strings"
	"testing"

	"github.com/mhsanaei/3x-ui/v3/internal/web/entity"
)

func TestLightsailSettingsRequireNamedProfileAndValidRegions(t *testing.T) {
	tests := []struct {
		name    string
		profile string
		regions string
		valid   bool
	}{
		{name: "named profile with a region target", profile: "xray-prod", regions: `[{"region":"us-east-1","bundleId":"small_3_0","blueprintId":"ubuntu_24_04","targetCount":2}]`, valid: true},
		{name: "empty profile cannot run automation", profile: "", regions: `[{"region":"us-east-1","bundleId":"small_3_0","blueprintId":"ubuntu_24_04","targetCount":2}]`},
		{name: "reject credential-like profile field", profile: "credential value with spaces", regions: `[{"region":"us-east-1","bundleId":"small_3_0","blueprintId":"ubuntu_24_04","targetCount":1}]`},
		{name: "reject negative target count", profile: "xray-prod", regions: `[{"region":"us-east-1","bundleId":"small_3_0","blueprintId":"ubuntu_24_04","targetCount":-1}]`},
		{name: "zero target is valid for owned resources only", profile: "xray-prod", regions: `[{"region":"us-east-1","bundleId":"small_3_0","blueprintId":"ubuntu_24_04","targetCount":0}]`, valid: true},
		{name: "reject incomplete target", profile: "xray-prod", regions: `[{"region":"us-east-1","targetCount":1}]`},
		{name: "reject duplicate regions", profile: "xray-prod", regions: `[{"region":"us-east-1","bundleId":"small_3_0","blueprintId":"ubuntu_24_04","targetCount":1},{"region":"us-east-1","bundleId":"medium_3_0","blueprintId":"ubuntu_24_04","targetCount":1}]`},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			settings := &entity.AllSetting{LightsailProfileName: tc.profile, LightsailRegionTargets: tc.regions, LightsailRestartTime: "04:00", LightsailTimeZone: "Asia/Shanghai", LightsailScaleEnabled: true, LightsailDailyRestartEnabled: true}
			err := validateLightsailSettings(settings)
			if tc.valid && err != nil {
				t.Fatalf("expected settings to be valid, got %v", err)
			}
			if !tc.valid && err == nil {
				t.Fatal("expected invalid Lightsail settings to be rejected")
			}
			if !tc.valid && strings.Contains(tc.profile, "credential") && !strings.Contains(err.Error(), "profile name") {
				t.Fatalf("error does not identify the safe profile-name field: %v", err)
			}
		})
	}
}

func TestLightsailSettingsPreparationDisablesUnwiredAutomation(t *testing.T) {
	targets := `[{"region":"us-east-1","bundleId":"small_3_0","blueprintId":"ubuntu_24_04","targetCount":1}]`
	tests := []struct {
		name string
		settings entity.AllSetting
	}{
		{name: "hourly reconciliation", settings: entity.AllSetting{LightsailProfileName: "xray-prod", LightsailRegionTargets: targets, LightsailScaleEnabled: true, LightsailRestartTime: "04:00", LightsailTimeZone: "Asia/Shanghai"}},
		{name: "daily stop and start", settings: entity.AllSetting{LightsailProfileName: "xray-prod", LightsailRegionTargets: targets, LightsailDailyRestartEnabled: true, LightsailRestartTime: "04:00", LightsailTimeZone: "Asia/Shanghai"}},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if err := applyLightsailDefaults(&tc.settings); err != nil {
				t.Fatalf("apply defaults: %v", err)
			}
			if tc.settings.LightsailScaleEnabled || tc.settings.LightsailDailyRestartEnabled {
				t.Fatal("lifecycle automation must normalize to disabled")
			}
			if err := validateLightsailSettings(&tc.settings); err != nil {
				t.Fatalf("valid non-executing settings were rejected: %v", err)
			}
		})
	}
}

func TestLightsailAutomationSettingsDefaultDisabledWithDailyRestartAtFourAMShanghai(t *testing.T) {
	settings := &entity.AllSetting{}
	if err := applyLightsailDefaults(settings); err != nil {
		t.Fatalf("apply defaults: %v", err)
	}
	if settings.LightsailRestartTime != "04:00" {
		t.Fatalf("restart time = %q, want 04:00", settings.LightsailRestartTime)
	}
	if settings.LightsailTimeZone != "Asia/Shanghai" {
		t.Fatalf("restart timezone = %q, want Asia/Shanghai", settings.LightsailTimeZone)
	}
	if settings.LightsailScaleEnabled || settings.LightsailDailyRestartEnabled {
		t.Fatal("automation must stay disabled until lifecycle execution is fully wired")
	}
}

func TestLightsailDefaultsForceUnwiredLifecycleAutomationOff(t *testing.T) {
	settings := &entity.AllSetting{LightsailScaleEnabled: true, LightsailDailyRestartEnabled: true}
	if err := applyLightsailDefaults(settings); err != nil {
		t.Fatalf("apply defaults: %v", err)
	}
	if settings.LightsailScaleEnabled || settings.LightsailDailyRestartEnabled {
		t.Fatal("unwired lifecycle settings must be normalized off")
	}
}

func TestLightsailFactoryDefaultsKeepRequestedAutomationEnabled(t *testing.T) {
	defaults := (&SettingService{}).GetFactoryDefaults()
	for key, want := range map[string]string{
		"lightsailScaleEnabled":        "false",
		"lightsailDailyRestartEnabled": "false",
		"lightsailRestartTime":         "04:00",
		"lightsailTimeZone":            "Asia/Shanghai",
	} {
		if got := defaults[key]; got != want {
			t.Errorf("factory default for %s = %q, want %q", key, got, want)
		}
	}
}
