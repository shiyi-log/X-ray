import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Alert, Button, Input, InputNumber, Select, Space, Switch, TimePicker } from 'antd';
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';

import type { AllSetting } from '@/models/setting';
import {
  parseLightsailRegionTargets,
  serializeLightsailRegionTargets,
} from '@/lib/lightsail/targets';
import { SettingListItem } from '@/components/ui';
import { HttpUtil } from '@/utils';

interface RegionInfo {
  name: string;
  displayName: string;
}
interface BundleInfo {
  id: string;
  name: string;
  price: number;
  active: boolean;
}
interface BlueprintInfo {
  id: string;
  name: string;
  version: string;
  active: boolean;
}
interface CatalogInfo {
  bundles: BundleInfo[];
  blueprints: BlueprintInfo[];
}

interface LightsailSettingsTabProps {
  allSetting: AllSetting;
  updateSetting: (patch: Partial<AllSetting>) => void;
}

export default function LightsailSettingsTab({
  allSetting,
  updateSetting,
}: LightsailSettingsTabProps) {
  const { t } = useTranslation();
  const [regions, setRegions] = useState<RegionInfo[]>([]);
  const [catalogs, setCatalogs] = useState<Record<string, CatalogInfo>>({});
  const [zones, setZones] = useState<Record<string, string[]>>({});
  const [accountId, setAccountId] = useState('');
  const [checkingProfile, setCheckingProfile] = useState(false);
  const targets = useMemo(() => {
    try {
      return parseLightsailRegionTargets(allSetting.lightsailRegionTargets);
    } catch {
      return [];
    }
  }, [allSetting.lightsailRegionTargets]);

  function updateTargets(next: typeof targets) {
    updateSetting({ lightsailRegionTargets: serializeLightsailRegionTargets(next) });
  }

  const usedRegions = useMemo(() => new Set(targets.map((target) => target.region)), [targets]);
  const regionChoices = regions.map((region) => region.name);
  const availableRegions = regionChoices.filter((region) => !usedRegions.has(region));

  async function loadCatalog(profileName: string, region: string) {
    const msg = await HttpUtil.post<CatalogInfo>(
      '/panel/api/setting/lightsail/catalog',
      { profileName, region },
      { silent: true },
    );
    if (msg.success && msg.obj) setCatalogs((current) => ({ ...current, [region]: msg.obj! }));
  }

  async function loadZones(profileName: string, region: string): Promise<string[]> {
    const msg = await HttpUtil.post<string[]>(
      '/panel/api/setting/lightsail/zones',
      { profileName, region },
      { silent: true },
    );
    const loaded = msg.success && Array.isArray(msg.obj) ? msg.obj : [];
    setZones((current) => ({ ...current, [region]: loaded }));
    return loaded;
  }

  async function verifyProfile() {
    const profileName = allSetting.lightsailProfileName.trim();
    setCheckingProfile(true);
    setAccountId('');
    try {
      const verified = await HttpUtil.post<{ accountId: string }>(
        '/panel/api/setting/lightsail/verifyProfile',
        { profileName },
        { silent: true },
      );
      if (!verified.success || !verified.obj?.accountId) return;
      const regionResult = await HttpUtil.post<RegionInfo[]>(
        '/panel/api/setting/lightsail/regions',
        { profileName },
        { silent: true },
      );
      if (!regionResult.success || !Array.isArray(regionResult.obj)) return;
      setAccountId(verified.obj.accountId);
      setRegions(regionResult.obj);
      await Promise.all(
        targets.flatMap((target) => [
          loadCatalog(profileName, target.region),
          loadZones(profileName, target.region),
        ]),
      );
    } finally {
      setCheckingProfile(false);
    }
  }

  return (
    <div className="lightsail-settings">
      <SettingListItem
        paddings="small"
        title={t('pages.settings.lightsail.profile')}
        description={t('pages.settings.lightsail.profileHint')}
      >
        <Input
          autoComplete="off"
          maxLength={64}
          value={allSetting.lightsailProfileName}
          placeholder="default"
          onChange={(event) => updateSetting({ lightsailProfileName: event.target.value.trim() })}
        />
        <Space style={{ marginTop: 8 }}>
          <Button loading={checkingProfile} onClick={() => void verifyProfile()}>
            Verify AWS profile
          </Button>
          {accountId && <span>Account: {accountId}</span>}
        </Space>
      </SettingListItem>

      <SettingListItem
        paddings="small"
        title={t('pages.settings.lightsail.regions')}
        description={t('pages.settings.lightsail.regionsHint')}
      >
        <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
          {regions.length === 0 && (
            <Alert
              type="info"
              showIcon
              title={t('pages.settings.lightsail.verifyProfileForRegions')}
            />
          )}
          {targets.map((target, index) => (
            <Space
              key={`${target.region}-${index}`}
              wrap
              size={[8, 8]}
              style={{ width: '100%' }}
              align="start"
            >
              <Select
                aria-label={t('pages.settings.lightsail.region')}
                style={{ width: 170 }}
                value={target.region}
                options={[
                  {
                    value: target.region,
                    label:
                      regions.find((region) => region.name === target.region)?.displayName ||
                      target.region,
                  },
                  ...regionChoices
                    .filter((region) => !usedRegions.has(region))
                    .map((region) => ({
                      value: region,
                      label: regions.find((row) => row.name === region)?.displayName || region,
                    })),
                ]}
                onChange={(region) => {
                  const next = [...targets];
                  next[index] = { ...target, region, availabilityZone: '' };
                  updateTargets(next);
                  if (allSetting.lightsailProfileName.trim()) {
                    void loadCatalog(allSetting.lightsailProfileName.trim(), region);
                    void loadZones(allSetting.lightsailProfileName.trim(), region);
                  }
                }}
              />
              <Select
                aria-label={t('pages.settings.lightsail.availabilityZone')}
                style={{ width: 170 }}
                value={target.availabilityZone || undefined}
                placeholder={t('pages.settings.lightsail.availabilityZone')}
                disabled={!zones[target.region]?.length}
                options={(zones[target.region] || []).map((zone) => ({ value: zone, label: zone }))}
                onChange={(availabilityZone) => {
                  const next = [...targets];
                  next[index] = { ...target, availabilityZone };
                  updateTargets(next);
                }}
              />
              <Select
                aria-label={t('pages.settings.lightsail.bundle')}
                style={{ width: 150 }}
                value={target.bundleId}
                options={
                  catalogs[target.region]
                    ? catalogs[target.region].bundles
                        .filter((bundle) => bundle.active)
                        .map((bundle) => ({
                          value: bundle.id,
                          label: bundle.name + ' - $' + bundle.price + '/mo',
                        }))
                    : []
                }
                onChange={(bundleId) => {
                  const next = [...targets];
                  next[index] = { ...target, bundleId };
                  updateTargets(next);
                }}
              />
              <Select
                aria-label={t('pages.settings.lightsail.blueprint')}
                style={{ width: 175 }}
                value={target.blueprintId}
                options={
                  catalogs[target.region]
                    ? catalogs[target.region].blueprints
                        .filter((blueprint) => blueprint.active)
                        .map((blueprint) => ({
                          value: blueprint.id,
                          label: blueprint.name + ' ' + blueprint.version,
                        }))
                    : []
                }
                onChange={(blueprintId) => {
                  const next = [...targets];
                  next[index] = { ...target, blueprintId };
                  updateTargets(next);
                }}
              />
              <InputNumber
                aria-label={t('pages.settings.lightsail.targetCount')}
                style={{ width: 105 }}
                min={0}
                max={1000}
                precision={0}
                value={target.targetCount}
                onChange={(targetCount) => {
                  if (targetCount == null) return;
                  const next = [...targets];
                  next[index] = { ...target, targetCount };
                  updateTargets(next);
                }}
              />
              <Button
                danger
                aria-label={t('pages.settings.lightsail.removeRegion')}
                icon={<DeleteOutlined aria-hidden />}
                onClick={() =>
                  updateTargets(targets.filter((_, targetIndex) => targetIndex !== index))
                }
              />
            </Space>
          ))}
          <Button
            icon={<PlusOutlined aria-hidden />}
            disabled={regions.length === 0 || availableRegions.length === 0}
            onClick={() => {
              const region = availableRegions[0];
              const profileName = allSetting.lightsailProfileName.trim();
              const existingZones = zones[region] || [];
              const addTarget = (availabilityZone: string) => {
                if (!availabilityZone) return;
                updateTargets([
                  ...targets,
                  {
                    region,
                    availabilityZone,
                    bundleId: 'small_3_0',
                    blueprintId: 'ubuntu_24_04',
                    targetCount: 1,
                  },
                ]);
              };
              if (existingZones.length) {
                addTarget(existingZones[0]);
              } else if (profileName) {
                void loadZones(profileName, region).then((loaded) => addTarget(loaded[0] || ''));
              }
              if (profileName) void loadCatalog(profileName, region);
            }}
          >
            {t('pages.settings.lightsail.addRegion')}
          </Button>
        </Space>
      </SettingListItem>

      <SettingListItem
        paddings="small"
        title={t('pages.settings.lightsail.hourlyReconcile')}
        description={t('pages.settings.lightsail.hourlyReconcileHint')}
      >
        <Switch checked={false} disabled />
      </SettingListItem>

      <SettingListItem
        paddings="small"
        title={t('pages.settings.lightsail.dailyRestart')}
        description={t('pages.settings.lightsail.dailyRestartHint')}
      >
        <Space wrap>
          <Switch checked={false} disabled />
          <TimePicker
            aria-label={t('pages.settings.lightsail.restartTime')}
            format="HH:mm"
            minuteStep={5}
            value={dayjs(`2000-01-01T${allSetting.lightsailRestartTime || '04:00'}`)}
            onChange={(time) =>
              time && updateSetting({ lightsailRestartTime: time.format('HH:mm') })
            }
            disabled
          />
          <span>{allSetting.lightsailTimeZone}</span>
        </Space>
      </SettingListItem>

      <Alert type="info" showIcon title={t('pages.settings.lightsail.lifecycleUnavailable')} />
    </div>
  );
}
