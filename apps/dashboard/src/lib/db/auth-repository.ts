import "server-only";

import { randomBytes, scryptSync, timingSafeEqual } from "node:crypto";
import { REQUIRED_ADMIN_EMAIL } from "@/lib/auth/admin-account-invariant";
import { dbQuery } from "@/lib/db/postgres";
import type { StaffRole } from "@/lib/permissions/matrix";

const ROLE_PRIORITY: StaffRole[] = ["owner", "admin", "operator", "viewer"];
const REQUIRED_ADMIN_PASSWORD =
  process.env.DASHBOARD_REQUIRED_ADMIN_PASSWORD ?? "admin123456!";

type UserRow = {
  id: string;
  email: string;
  password_hash: string;
  must_change_password: boolean;
  is_active: boolean;
};

type RoleRow = { name: StaffRole };

type GroupAssignmentRow = { provider_group_id: string };

function toDisplayName(email: string): string {
  const localPart = email.split("@")[0] ?? "staff";
  return localPart
    .replace(/[._-]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function pickHighestRole(roles: StaffRole[]): StaffRole {
  for (const role of ROLE_PRIORITY) {
    if (roles.includes(role)) {
      return role;
    }
  }

  return "viewer";
}

let bcryptCompareFn: ((password: string, hash: string) => Promise<boolean>) | null | undefined;

async function loadBcryptCompareFn(): Promise<
  ((password: string, hash: string) => Promise<boolean>) | null
> {
  if (bcryptCompareFn !== undefined) {
    return bcryptCompareFn;
  }

  try {
    const runtimeRequire = (0, eval)("require") as (id: string) => { compare?: unknown };
    const mod = runtimeRequire("bcryptjs");
    bcryptCompareFn =
      typeof mod.compare === "function"
        ? (mod.compare as (password: string, hash: string) => Promise<boolean>)
        : null;
  } catch {
    bcryptCompareFn = null;
  }

  return bcryptCompareFn;
}

function hashPasswordWithScrypt(password: string): string {
  const salt = randomBytes(16).toString("hex");
  const digest = scryptSync(password, salt, 64).toString("hex");
  return `scrypt:${salt}:${digest}`;
}

function verifyScryptPassword(password: string, encodedHash: string): boolean {
  const [scheme, salt, storedDigest] = encodedHash.split(":");
  if (scheme !== "scrypt" || !salt || !storedDigest) {
    return false;
  }

  const derivedDigest = scryptSync(password, salt, 64).toString("hex");
  return timingSafeEqual(Buffer.from(derivedDigest, "hex"), Buffer.from(storedDigest, "hex"));
}

/**
 * `kuuna_backend` uses `scrypt$N$r$p$<salt_hex>$<digest_hex>` (see
 * `hash_password` in `backend/src/kuuna_backend/domain/auth/service.py`). Dashboard
 * bootstraps with a different `scrypt:...` encoding; users first created via the
 * API/backend must be verified with this path.
 */
function verifyBackendScryptPassword(password: string, encodedHash: string): boolean {
  const parts = encodedHash.split("$");
  if (parts.length < 6 || parts[0] !== "scrypt") {
    return false;
  }
  const N = Number.parseInt(parts[1] ?? "", 10);
  const r = Number.parseInt(parts[2] ?? "", 10);
  const p = Number.parseInt(parts[3] ?? "", 10);
  const saltHex = parts[4] ?? "";
  const digestHex = parts.slice(5).join("$");
  if (!Number.isFinite(N) || !Number.isFinite(r) || !Number.isFinite(p) || !saltHex || !digestHex) {
    return false;
  }
  const salt = Buffer.from(saltHex, "hex");
  const expected = Buffer.from(digestHex, "hex");
  if (expected.length === 0) {
    return false;
  }
  const maxmem = 256 * 1024 * r * Math.max(1, p);
  let derived: Buffer;
  try {
    derived = scryptSync(password, salt, expected.length, {
      N,
      r,
      p,
      maxmem: Math.max(maxmem, 32 * 1024 * 1024),
    });
  } catch {
    return false;
  }
  return derived.length === expected.length && timingSafeEqual(derived, expected);
}

async function verifyPassword(password: string, passwordHash: string): Promise<boolean> {
  if (passwordHash.startsWith("$2")) {
    const compare = await loadBcryptCompareFn();
    if (!compare) {
      return false;
    }
    return compare(password, passwordHash);
  }

  if (passwordHash.startsWith("scrypt$")) {
    return verifyBackendScryptPassword(password, passwordHash);
  }

  if (passwordHash.startsWith("scrypt:")) {
    return verifyScryptPassword(password, passwordHash);
  }

  if (passwordHash.startsWith("plain:")) {
    return password === passwordHash.slice("plain:".length);
  }

  return password === passwordHash;
}

export type DbSessionUser = {
  userId: string;
  email: string;
  displayName: string;
  role: StaffRole;
  assignedGroupIds: string[];
  mustChangePassword: boolean;
  isActive: boolean;
};

export async function ensureRequiredAdminAccount(): Promise<void> {
  await dbQuery(
    `
    insert into roles (name)
    values ('owner'), ('admin'), ('operator'), ('viewer')
    on conflict (name) do nothing
    `,
  );

  let adminId: string | undefined;
  const existingAdmin = await dbQuery<{ id: string }>(
    `
    select id::text
    from users
    where lower(email) = lower($1)
    limit 1
    `,
    [REQUIRED_ADMIN_EMAIL],
  );

  if (existingAdmin.length) {
    adminId = existingAdmin[0].id;
  } else {
    const bootstrapHash = hashPasswordWithScrypt(REQUIRED_ADMIN_PASSWORD);
    const inserted = await dbQuery<{ id: string }>(
      `
      insert into users (email, password_hash, must_change_password, is_active, failed_login_attempts)
      values ($1, $2, true, true, 0)
      returning id::text
      `,
      [REQUIRED_ADMIN_EMAIL, bootstrapHash],
    );
    adminId = inserted[0]?.id;
  }

  if (!adminId) {
    return;
  }

  if (
    process.env.DASHBOARD_DEV_RESET_BOOTSTRAP_ADMIN_PASSWORD === "1" &&
    process.env.NODE_ENV !== "production"
  ) {
    const resetHash = hashPasswordWithScrypt(REQUIRED_ADMIN_PASSWORD);
    await dbQuery(
      `
      update users
      set password_hash = $2,
          must_change_password = true,
          updated_at = now()
      where id = $1::uuid
      `,
      [adminId, resetHash],
    );
  }

  await dbQuery(
    `
    update users
    set is_active = true,
        updated_at = now()
    where id = $1::uuid
    `,
    [adminId],
  );

  const adminRole = await dbQuery<{ id: string }>(
    `
    select id::text from roles where name = 'admin' limit 1
    `,
  );

  if (!adminRole.length) {
    return;
  }

  await dbQuery(
    `
    insert into user_roles (user_id, role_id)
    values ($1::uuid, $2::uuid)
    on conflict (user_id, role_id) do nothing
    `,
    [adminId, adminRole[0].id],
  );
}

export async function authenticateUser(
  email: string,
  password: string,
): Promise<DbSessionUser | null> {
  const users = await dbQuery<UserRow>(
    `
    select id::text, email, password_hash, must_change_password, is_active
    from users
    where lower(email) = lower($1)
    limit 1
    `,
    [email],
  );

  const user = users[0];
  if (!user) {
    return null;
  }

  const validPassword = await verifyPassword(password, user.password_hash);
  if (!validPassword) {
    return null;
  }

  const roles = await dbQuery<RoleRow>(
    `
    select r.name::text as name
    from user_roles ur
    join roles r on r.id = ur.role_id
    where ur.user_id = $1::uuid
    `,
    [user.id],
  );

  const assignments = await dbQuery<GroupAssignmentRow>(
    `
    select provider_group_id
    from group_assignments
    where user_id = $1::uuid
    order by provider_group_id asc
    `,
    [user.id],
  );

  const role = pickHighestRole(roles.map((item) => item.name));

  return {
    userId: user.id,
    email: user.email,
    displayName: toDisplayName(user.email),
    role,
    assignedGroupIds: assignments.map((item) => item.provider_group_id),
    mustChangePassword: user.must_change_password,
    isActive: user.is_active,
  };
}

export async function updateUserPassword(
  userId: string,
  password: string,
): Promise<void> {
  const passwordHash = hashPasswordWithScrypt(password);

  await dbQuery(
    `
    update users
    set password_hash = $2,
        must_change_password = false,
        updated_at = now()
    where id = $1::uuid
    `,
    [userId, passwordHash],
  );
}
