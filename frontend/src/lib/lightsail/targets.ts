export interface LightsailRegionTarget {
  region: string;
  availabilityZone: string;
  bundleId: string;
  blueprintId: string;
  targetCount: number;
}

export function parseLightsailRegionTargets(value: string): LightsailRegionTarget[] {
  const parsed: unknown = JSON.parse(value || '[]');
  if (!Array.isArray(parsed)) throw new Error('Lightsail region targets must be an array');

  const seenRegions = new Set<string>();
  return parsed.map((entry, index) => {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
      throw new Error(`Lightsail region target ${index + 1} is invalid`);
    }
    const row = entry as Record<string, unknown>;
    const region = typeof row.region === 'string' ? row.region.trim() : '';
    const availabilityZone =
      typeof row.availabilityZone === 'string' ? row.availabilityZone.trim() : '';
    const bundleId = typeof row.bundleId === 'string' ? row.bundleId.trim() : '';
    const blueprintId = typeof row.blueprintId === 'string' ? row.blueprintId.trim() : '';
    const targetCount = row.targetCount;
    if (!/^[a-z]{2}-(?:[a-z]+-)+[0-9]+$/.test(region)) {
      throw new Error(`Lightsail region target ${index + 1} needs a valid region`);
    }
    if (
      availabilityZone &&
      (availabilityZone.length !== region.length + 1 ||
        !availabilityZone.startsWith(region) ||
        !/[a-z]$/.test(availabilityZone))
    ) {
      throw new Error('Lightsail region target needs a valid availability zone');
    }
    if (seenRegions.has(region)) throw new Error(`Lightsail region ${region} is duplicated`);
    if (!/^[a-z][a-z0-9_]*$/.test(bundleId)) {
      throw new Error(`Lightsail region target ${index + 1} needs a bundle`);
    }
    if (!/^[a-z][a-z0-9_]*$/.test(blueprintId)) {
      throw new Error(`Lightsail region target ${index + 1} needs a blueprint`);
    }
    if (!Number.isInteger(targetCount) || Number(targetCount) < 0 || Number(targetCount) > 1000) {
      throw new Error(`Lightsail region target ${index + 1} count must be between 0 and 1000`);
    }
    seenRegions.add(region);
    return { region, availabilityZone, bundleId, blueprintId, targetCount: Number(targetCount) };
  });
}

export function serializeLightsailRegionTargets(targets: LightsailRegionTarget[]): string {
  return JSON.stringify(parseLightsailRegionTargets(JSON.stringify(targets)));
}
