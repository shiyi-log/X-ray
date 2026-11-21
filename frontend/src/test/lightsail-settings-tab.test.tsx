import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';

import LightsailSettingsTab from '@/pages/settings/LightsailSettingsTab';
import { AllSetting } from '@/models/setting';
import { renderWithProviders } from './test-utils';
import { HttpUtil } from '@/utils';

beforeEach(() => {
  vi.spyOn(HttpUtil, 'post')
    .mockReset()
    .mockResolvedValue({ success: true, obj: {} } as never);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('Lightsail settings tab', () => {
  it('adds a region target with an explicit plan after loading the AWS region catalog', async () => {
    vi.spyOn(HttpUtil, 'post')
      .mockResolvedValueOnce({
        success: true,
        msg: '',
        obj: { accountId: '123456789012' },
      } as never)
      .mockResolvedValueOnce({
        success: true,
        msg: '',
        obj: [{ name: 'us-east-1', displayName: 'Virginia' }],
      } as never)
      .mockResolvedValueOnce({
        success: true,
        msg: '',
        obj: ['us-east-1a', 'us-east-1b'],
      } as never)
      .mockResolvedValueOnce({
        success: true,
        msg: '',
        obj: {
          bundles: [{ id: 'small_3_0', name: 'Small', price: 12, active: true }],
          blueprints: [{ id: 'ubuntu_24_04', name: 'Ubuntu', version: '24.04', active: true }],
        },
      } as never);
    const updateSetting = vi.fn();
    const settings = new AllSetting({ lightsailProfileName: 'xray-prod' });
    renderWithProviders(
      <LightsailSettingsTab allSetting={settings} updateSetting={updateSetting} />,
    );

    fireEvent.click(screen.getByRole('button', { name: /verify aws profile/i }));
    const addRegion = await screen.findByRole('button', { name: 'Add region' });
    await waitFor(() => expect((addRegion as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(addRegion as HTMLButtonElement);
    await waitFor(() =>
      expect(updateSetting).toHaveBeenCalledWith({
        lightsailRegionTargets:
          '[{"region":"us-east-1","availabilityZone":"us-east-1a","bundleId":"small_3_0","blueprintId":"ubuntu_24_04","targetCount":1}]',
      }),
    );
  });

  it('never writes an AWS credential into settings when changing the profile reference', () => {
    const updateSetting = vi.fn();
    renderWithProviders(
      <LightsailSettingsTab allSetting={new AllSetting()} updateSetting={updateSetting} />,
    );

    fireEvent.change(screen.getByPlaceholderText('default'), {
      target: { value: 'panel-node-pool' },
    });

    expect(updateSetting).toHaveBeenCalledWith({ lightsailProfileName: 'panel-node-pool' });
  });

  it('keeps lifecycle automation disabled until provisioning and scheduling are wired', () => {
    renderWithProviders(
      <LightsailSettingsTab allSetting={new AllSetting()} updateSetting={vi.fn()} />,
    );

    const switches = screen.getAllByRole('switch');
    expect(switches).toHaveLength(2);
    for (const control of screen.getAllByRole('switch')) {
      expect((control as HTMLButtonElement).disabled).toBe(true);
    }
    expect(
      screen.getByText(/Automatic scaling, daily restart, node registration/),
    ).toBeTruthy();
  });

  it('offers all 19 current Lightsail instance regions', async () => {
    vi.spyOn(HttpUtil, 'post')
      .mockResolvedValueOnce({
        success: true,
        msg: '',
        obj: { accountId: '123456789012' },
      } as never)
      .mockResolvedValueOnce({
        success: true,
        msg: '',
        obj: [
          'us-east-1',
          'us-east-2',
          'us-west-2',
          'ap-east-1',
          'ap-southeast-3',
          'ap-southeast-5',
          'ap-south-1',
          'ap-northeast-2',
          'ap-southeast-1',
          'ap-southeast-2',
          'ap-northeast-1',
          'ca-central-1',
          'eu-central-1',
          'eu-west-1',
          'eu-west-2',
          'eu-west-3',
          'eu-north-1',
          'eu-south-2',
          'sa-east-1',
        ].map((name) => ({ name, displayName: name })),
      } as never)
      .mockResolvedValueOnce({
        success: true,
        msg: '',
        obj: { bundles: [], blueprints: [] },
      } as never);
    const setting = new AllSetting({
      lightsailProfileName: 'panel-node-pool',
      lightsailRegionTargets:
        '[{"region":"us-east-1","bundleId":"small_3_0","blueprintId":"ubuntu_24_04","targetCount":1}]',
    });
    renderWithProviders(<LightsailSettingsTab allSetting={setting} updateSetting={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /verify aws profile/i }));
    await screen.findByText(/123456789012/);

    const regionSelect = document.querySelector('.ant-select');
    expect(regionSelect).not.toBeNull();
    fireEvent.mouseDown(regionSelect as Element);
    const visibleOptions = () =>
      Array.from(document.querySelectorAll('.ant-select-item-option')).map((option) =>
        option.textContent?.trim(),
      );
    const regionOptions = visibleOptions();
    const list = document.querySelector('.ant-select-dropdown-list-holder');
    expect(list).not.toBeNull();
    fireEvent.scroll(list as Element, { target: { scrollTop: 1000 } });
    await waitFor(() => expect(visibleOptions()).toContain('sa-east-1'));
    regionOptions.push(...visibleOptions());
    expect(new Set(regionOptions).size).toBe(19);
    expect(regionOptions).toContain('ap-east-1');
    expect(regionOptions).toContain('ap-southeast-5');
    expect(regionOptions).toContain('eu-south-2');
    expect(regionOptions).not.toContain('us-west-1');
  });

  it('checks the named profile and never sends AWS secrets from the panel', async () => {
    const post = vi
      .spyOn(HttpUtil, 'post')
      .mockResolvedValueOnce({
        success: true,
        msg: '',
        obj: { accountId: '123456789012' },
      } as never)
      .mockResolvedValueOnce({
        success: true,
        msg: '',
        obj: [{ name: 'ap-southeast-1', displayName: 'Singapore' }],
      } as never)
      .mockResolvedValueOnce({
        success: true,
        msg: '',
        obj: {
          bundles: [{ id: 'small_3_0', name: 'Small', price: 12, active: true }],
          blueprints: [{ id: 'ubuntu_24_04', name: 'Ubuntu', version: '24.04', active: true }],
        },
      } as never);
    const setting = new AllSetting();
    setting.lightsailProfileName = 'panel-node-pool';
    setting.lightsailRegionTargets =
      '[{"region":"ap-southeast-1","bundleId":"small_3_0","blueprintId":"ubuntu_24_04","targetCount":1}]';
    renderWithProviders(<LightsailSettingsTab allSetting={setting} updateSetting={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: /verify aws profile/i }));

    expect(await screen.findByText(/123456789012/)).toBeTruthy();
    expect(await screen.findByText('Small - $12/mo')).toBeTruthy();
    expect(post).toHaveBeenNthCalledWith(
      1,
      '/panel/api/setting/lightsail/verifyProfile',
      { profileName: 'panel-node-pool' },
      { silent: true },
    );
    expect(post.mock.calls.flat().join(' ')).not.toMatch(/secretAccessKey|accessKeyId|password/i);
    post.mockRestore();
  });
});
