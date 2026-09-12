/**
 * Who is signed in, according to the hub.
 *
 * This module exists because of a bug worth recording. The lab used to work out
 * the learner's identity by parsing the launch token itself — and the launch
 * token is not a JWT. `generateLabToken` on the hub produces
 * `base64url(payload).hmacSignature`: two segments, not three. Reading
 * `segments[1]` therefore read the *signature*, decoding it produced binary,
 * `JSON.parse` threw, the throw was swallowed, and every learner on a given
 * browser fell through to one shared fallback identity. The visible symptom was
 * that everybody saw the same project history.
 *
 * The lesson generalises: the lab should never have been parsing a token it
 * does not issue and cannot verify. `POST /api/auth/authorize-lab` already
 * returns the verified user — id, email, name and role — and the hub is the
 * only party that can verify anything, because it holds the signing secret.
 * So the identity comes from the authorization response and nowhere else.
 *
 * Nothing here is trusted for authorisation of anything that matters. The hub
 * decides whether the session is valid; this module only remembers what the hub
 * said, so the interface can scope storage and address the learner by name.
 */

export interface LabIdentity {
  /** The hub's user id. Stable across logins and devices — the key everything scopes by. */
  userId: string;
  email: string | null;
  name: string | null;
  /** The hub's role string: USER, ADMIN, SUPER_ADMIN, … */
  role: string;
  /** Which lab the hub authorised this session for. */
  labId: string | null;
  labSlug: string | null;
  /**
   * Whether the hub marks this account as an expert reviewer.
   *
   * Used only to decide whether to offer the review form. It is not an
   * authorisation: the review endpoint re-reads the flag from the database on
   * every call, because anything this browser holds is something this browser
   * could have edited.
   */
  isReviewer: boolean;
}

/**
 * Held in memory, and mirrored to sessionStorage so a reload inside the same
 * tab does not lose it before the guard has re-verified. It is deliberately not
 * in localStorage: an identity that outlived the session would be a claim about
 * who is signed in that nobody had checked.
 */
const STORAGE_KEY = '__lab_identity';

let current: LabIdentity | null = null;
const listeners = new Set<(identity: LabIdentity | null) => void>();

function readStored(): LabIdentity | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<LabIdentity>;
    if (typeof parsed.userId !== 'string' || parsed.userId === '') return null;
    return {
      userId: parsed.userId,
      email: typeof parsed.email === 'string' ? parsed.email : null,
      name: typeof parsed.name === 'string' ? parsed.name : null,
      role: typeof parsed.role === 'string' ? parsed.role : 'USER',
      labId: typeof parsed.labId === 'string' ? parsed.labId : null,
      labSlug: typeof parsed.labSlug === 'string' ? parsed.labSlug : null,
      isReviewer: parsed.isReviewer === true,
    };
  } catch {
    return null;
  }
}

/** Record the identity the hub returned. Called only by the auth guard. */
export function setIdentity(identity: LabIdentity | null): void {
  current = identity;
  try {
    if (identity) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(identity));
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* Private mode. The in-memory copy still serves this page load. */
  }
  for (const listener of listeners) listener(identity);
}

export function getIdentity(): LabIdentity | null {
  if (current) return current;
  current = readStored();
  return current;
}

export function subscribeToIdentity(listener: (identity: LabIdentity | null) => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/**
 * Build an identity from the authorize-lab response body.
 *
 * Returns null rather than a partial identity when the response carries no user
 * id. A session we cannot name is one we must not scope storage by — quietly
 * inventing a placeholder is how everyone ended up sharing a history in the
 * first place.
 */
export function identityFromAuthResponse(body: unknown): LabIdentity | null {
  if (typeof body !== 'object' || body === null) return null;
  const { user, lab } = body as { user?: Record<string, unknown>; lab?: Record<string, unknown> };
  const userId = user?.id;
  if (typeof userId !== 'string' || userId.trim() === '') return null;

  return {
    userId: userId.trim(),
    email: typeof user?.email === 'string' ? user.email : null,
    name: typeof user?.name === 'string' ? user.name : null,
    role: typeof user?.role === 'string' && user.role.trim() !== '' ? user.role.trim().toUpperCase() : 'USER',
    labId: typeof lab?.id === 'string' ? lab.id : null,
    labSlug: typeof lab?.slug === 'string' ? lab.slug : null,
    // Absent means false. A hub that has not been updated yet simply offers no
    // review form, which is the safe direction for a missing field.
    isReviewer: user?.isReviewer === true,
  };
}

/* ------------------------------------------------------------------ *
 * Roles
 * ------------------------------------------------------------------ */

/**
 * Roles the hub treats as platform administration.
 *
 * SUPER_ADMIN and nothing else. `hasLabAccess` on the hub short-circuits for
 * that role alone, so it is the one that already means "every lab"; including
 * ADMIN here made this lab disagree with the platform about what an
 * administrator is, and handed every mode to a role the hub would not even let
 * through the door without a separate grant.
 *
 * A set rather than a string comparison so that adding a role is one edit in
 * one place, and so a reader can see exactly which roles are elevated.
 */
const ADMIN_ROLES = new Set(['SUPER_ADMIN']);

export function isAdmin(identity: LabIdentity | null): boolean {
  return identity !== null && ADMIN_ROLES.has(identity.role);
}

/** How to describe the signed-in learner on screen. Never shows a bare id. */
export function displayName(identity: LabIdentity | null): string {
  if (!identity) return 'Not signed in';
  return identity.name?.trim() || identity.email?.trim() || 'Signed-in learner';
}

/* ------------------------------------------------------------------ *
 * Per-learner storage scoping
 * ------------------------------------------------------------------ */

/** FNV-1a. Short, stable, and adequate for turning an identity into a key. */
function fingerprint(value: string): string {
  let hash = 2166136261;
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}

/**
 * The storage namespace for whoever is signed in.
 *
 * Every hub-session key in this lab hangs off this: the feedback draft and the
 * local copy of a review in progress. It exists because getting it wrong is not
 * a cosmetic bug: browser storage is shared by everyone who uses the machine,
 * so an unscoped key means the next person to sign in inherits the last
 * person's half-written review, under their own name.
 *
 * The hub's user id is stable across logins and devices, which is what makes it
 * the right basis. It is fingerprinted rather than used raw so that no account
 * identifier is written into a storage key: a key is as much a record as a
 * value, and this one is written on a machine the reviewer does not own.
 *
 * With no verified identity the scope is `anon`, and everything stored under it
 * belongs to the browser rather than to a person. That is stated on screen
 * rather than left to look like an account.
 */
export function storageScope(): string {
  const identity = getIdentity();
  return identity ? `u-${fingerprint(identity.userId)}` : 'anon';
}

/** A storage key belonging to the signed-in learner rather than the browser. */
export function scopedKey(base: string): string {
  return `${base}.${storageScope()}`;
}
