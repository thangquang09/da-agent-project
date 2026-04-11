const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

export function toBackendAssetUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  if (/^https?:\/\//i.test(url)) return url;
  if (!url.startsWith("/")) return `${API_URL}/${url}`;
  return `${API_URL}${url}`;
}
