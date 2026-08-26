const AUTHOR_KEY_STORAGE = "sober_alone_author_key_v1";

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

export const AUTHOR_KEY_HEADER = "X-Sober-Author-Key";
