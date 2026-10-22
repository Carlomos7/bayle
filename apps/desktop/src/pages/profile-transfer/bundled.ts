/** The shell's hand-over of a download that ships .me3 profiles (Qt: open_profile_import). The shell calls
 * handOverBundled(...) and navigates to /profile-transfer; the page takes it on mount, or at once when already open. */
export interface BundledRequest {
  /** The unpacked download's folder. */
  unpacked: string;
  /** The .me3 paths inside it. */
  profiles: string[];
  /** A folder the backend deletes when the import is done or left. */
  staging?: string;
}

let pending: BundledRequest | null = null;
const listeners = new Set<() => void>();

export function handOverBundled(req: BundledRequest) {
  pending = req;
  listeners.forEach((l) => l());
}

export function takeBundled(): BundledRequest | null {
  const r = pending;
  pending = null;
  return r;
}

export function onBundled(listener: () => void) {
  listeners.add(listener);
  return () => void listeners.delete(listener);
}
