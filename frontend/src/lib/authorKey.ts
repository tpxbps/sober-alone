const AUTHOR_KEY_STORAGE = "sober_alone_author_key_v1";
const LEGACY_OWNER_STORAGE = "scriptOwnerIds";
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const UUID_SCAN_PATTERN = /[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/gi;

export function getStoredAuthorKey(): string | null {
  return localStorage.getItem(AUTHOR_KEY_STORAGE);
}

export function getOrCreateAuthorKey(): string {
  const existing = getStoredAuthorKey();
  if (existing) return existing;

  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  const key = btoa(String.fromCharCode(...bytes))
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replaceAll("=", "");
  localStorage.setItem(AUTHOR_KEY_STORAGE, key);
  return key;
}

export function getLegacyOwnerUuids(): string[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(LEGACY_OWNER_STORAGE) || "[]");
    if (!Array.isArray(parsed)) return [];
    return [...new Set(parsed.filter((value): value is string =>
      typeof value === "string" && UUID_PATTERN.test(value),
    ))];
  } catch {
    return [];
  }
}

export function parseLegacyOwnerUuids(value: string): string[] {
  return [...new Set((value.match(UUID_SCAN_PATTERN) || []).map((id) => id.toLowerCase()))];
}

export function storeLegacyOwnerUuids(values: string[]): void {
  const validValues = [...new Set(values.filter((value) => UUID_PATTERN.test(value)))];
  if (validValues.length === 0) {
    clearLegacyOwnerUuids();
    return;
  }
  localStorage.setItem(LEGACY_OWNER_STORAGE, JSON.stringify(validValues));
}

export function clearLegacyOwnerUuids(): void {
  localStorage.removeItem(LEGACY_OWNER_STORAGE);
}

export const AUTHOR_KEY_HEADER = "X-Sober-Author-Key";
