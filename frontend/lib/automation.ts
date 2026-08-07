import { createHash } from 'node:crypto';
import { parse, stringify } from 'smol-toml';

export const AUTOMATION_SCHEMA_VERSION = 1;
export const AUTOMATION_MAX_BYTES = 256 * 1024;

const REQUIRED_KEYS = [
  'schema_version',
  'name',
  'description',
  'platform',
  'format',
  'version',
  'schedule_type',
  'timezone',
  'trigger',
  'required_permissions',
  'required_connectors',
  'workspace_required',
  'delivery_type',
  'tested_on',
  'tags',
  'license',
  'enabled',
] as const;

const KNOWN_KEYS = new Set<string>([
  ...REQUIRED_KEYS,
  'required_secrets',
  'related_prompts',
  'related_skills',
  'related_mcps',
  'notes',
]);

const SCHEDULE_TYPES = new Set(['manual', 'interval', 'cron', 'daily', 'weekly', 'monthly']);
const DELIVERY_TYPES = new Set(['none', 'thread', 'channel', 'email', 'webhook', 'file']);
const SEMVER = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/;
const EMAIL = /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/i;
const ABSOLUTE_PATH =
  /(?:^|[\s"'=])(?:[A-Za-z]:[\\/]|\\\\[^\\\s]+\\|\/(?:Users|home|root|var\/run|mnt\/[a-z])\/)/i;
const DESTRUCTIVE_COMMAND =
  /\b(?:rm\s+-[^\n]*r[^\n]*f|git\s+reset\s+--hard|git\s+clean\s+-[^\n]*f|drop\s+(?:database|table)|truncate\s+table|shutdown\b|format\s+[A-Za-z]:|Remove-Item[^\n]*-Recurse[^\n]*-Force)\b/i;
const SENSITIVE_ASSIGNMENT =
  /^\s*(?:api[_-]?key|token|password|cookie|authorization|client[_-]?secret|webhook[_-]?url)\s*=\s*["']?([^"'\s#][^#\r\n]*)/gim;
const PLACEHOLDER =
  /^(?:<[^>]+>|\$\{[A-Z][A-Z0-9_]*\}|\{\{[A-Z][A-Z0-9_]*\}\}|REPLACE_ME|CHANGEME)$/i;
const SECRET_VALUE =
  /(?:\bBearer\s+[A-Za-z0-9._~+/=-]{12,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\b(?:ghp|github_pat|glpat|sk)-[A-Za-z0-9_-]{12,})/i;
const CREDENTIAL_URL = /https?:\/\/[^/\s:@]+:[^@\s/]+@/i;

export type AutomationFindingSeverity = 'error' | 'warning';

export interface AutomationFinding {
  code: string;
  severity: AutomationFindingSeverity;
  path: string;
  message: string;
}

export interface AutomationConfig {
  schema_version: number;
  name: string;
  description: string;
  platform: string;
  format: 'automation';
  version: string;
  schedule_type: string;
  timezone: string;
  trigger: string;
  required_permissions: string[];
  required_connectors: string[];
  workspace_required: boolean;
  delivery_type: string;
  tested_on: string[];
  tags: string[];
  license: string;
  enabled: boolean;
  required_secrets?: string[];
  related_prompts?: string[];
  related_skills?: string[];
  related_mcps?: string[];
  notes?: string;
}

export interface AutomationSource {
  owner: string;
  repo: string;
  ref: string;
  sha?: string;
}

export interface AutomationPreflight {
  ok: boolean;
  config: AutomationConfig | null;
  findings: AutomationFinding[];
  source: AutomationSource | null;
  sourceHash: string;
  compatible: boolean;
  importState: 'disabled';
}

export interface AutomationBundleOptions {
  acknowledgeWarnings?: boolean;
}

function finding(
  code: string,
  severity: AutomationFindingSeverity,
  path: string,
  message: string,
): AutomationFinding {
  return { code, severity, path, message };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function stringValue(
  table: Record<string, unknown>,
  key: string,
  findings: AutomationFinding[],
): string {
  const value = table[key];
  if (typeof value !== 'string' || !value.trim()) {
    findings.push(finding('invalid_string', 'error', key, `${key} must be a non-empty string.`));
    return '';
  }
  return value.trim();
}

function booleanValue(
  table: Record<string, unknown>,
  key: string,
  findings: AutomationFinding[],
): boolean {
  const value = table[key];
  if (typeof value !== 'boolean') {
    findings.push(finding('invalid_boolean', 'error', key, `${key} must be a boolean.`));
    return false;
  }
  return value;
}

function stringArray(
  table: Record<string, unknown>,
  key: string,
  findings: AutomationFinding[],
  optional = false,
): string[] | undefined {
  const value = table[key];
  if (optional && value === undefined) return undefined;
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string')) {
    findings.push(
      finding('invalid_string_array', 'error', key, `${key} must be an array of strings.`),
    );
    return [];
  }
  const normalized = [...new Set(value.map((item) => item.trim()).filter(Boolean))];
  if (normalized.length > 100) {
    findings.push(finding('array_too_large', 'error', key, `${key} cannot exceed 100 entries.`));
  }
  return normalized.slice(0, 100);
}

function privateHost(value: string): boolean {
  try {
    const url = new URL(value);
    const host = url.hostname.toLowerCase();
    if (
      host === 'localhost' ||
      host === '127.0.0.1' ||
      host === '::1' ||
      host.endsWith('.local') ||
      host.endsWith('.internal')
    ) {
      return true;
    }
    if (/^10\./.test(host) || /^192\.168\./.test(host)) return true;
    const match = host.match(/^172\.(\d{1,3})\./);
    return Boolean(match && Number(match[1]) >= 16 && Number(match[1]) <= 31);
  } catch {
    return false;
  }
}

function scanScalar(
  value: string,
  path: string,
  findings: AutomationFinding[],
): void {
  if (EMAIL.test(value)) {
    findings.push(
      finding('email_address', 'error', path, 'Replace email addresses with a named placeholder.'),
    );
  }
  if (ABSOLUTE_PATH.test(value)) {
    findings.push(
      finding(
        'absolute_path',
        'error',
        path,
        'Replace machine-specific absolute paths with a workspace placeholder.',
      ),
    );
  }
  for (const token of value.match(/https?:\/\/[^\s"'<>]+/gi) || []) {
    if (privateHost(token)) {
      findings.push(
        finding('private_url', 'error', path, 'Private and local URLs cannot be published.'),
      );
    }
  }
  if (DESTRUCTIVE_COMMAND.test(value)) {
    findings.push(
      finding(
        'destructive_command',
        'error',
        path,
        'Destructive commands are not allowed in a public Automation package.',
      ),
    );
  }
  if (SECRET_VALUE.test(value) || CREDENTIAL_URL.test(value)) {
    findings.push(
      finding(
        'embedded_secret',
        'error',
        path,
        'A credential-like value is embedded in the public TOML.',
      ),
    );
  }
  if (/(?:thread|channel)[_-]?id/i.test(path) && /\d{5,}/.test(value)) {
    findings.push(
      finding(
        'delivery_identifier',
        'error',
        path,
        'Replace thread and channel identifiers with named parameters.',
      ),
    );
  }
}

function scanTable(
  table: Record<string, unknown>,
  findings: AutomationFinding[],
  prefix = '',
): void {
  for (const [key, value] of Object.entries(table)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === 'string') {
      scanScalar(value, path, findings);
    } else if (Array.isArray(value)) {
      value.forEach((item, index) => {
        if (typeof item === 'string') scanScalar(item, `${path}[${index}]`, findings);
        else if (isRecord(item)) scanTable(item, findings, `${path}[${index}]`);
      });
    } else if (isRecord(value)) {
      scanTable(value, findings, path);
    }
  }
}

function deduplicateFindings(findings: AutomationFinding[]): AutomationFinding[] {
  const seen = new Set<string>();
  return findings.filter((item) => {
    const key = `${item.code}:${item.path}:${item.message}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function inspectAutomationToml(
  raw: string,
  source: AutomationSource | null = null,
): AutomationPreflight {
  const findings: AutomationFinding[] = [];
  const sourceHash = createHash('sha256').update(raw, 'utf8').digest('hex');
  if (Buffer.byteLength(raw, 'utf8') > AUTOMATION_MAX_BYTES) {
    findings.push(
      finding(
        'file_too_large',
        'error',
        'automation.toml',
        `automation.toml exceeds ${AUTOMATION_MAX_BYTES} bytes.`,
      ),
    );
    return {
      ok: false,
      config: null,
      findings,
      source,
      sourceHash,
      compatible: false,
      importState: 'disabled',
    };
  }

  let table: Record<string, unknown>;
  try {
    const parsed = parse(raw);
    if (!isRecord(parsed)) throw new Error('root is not a table');
    table = parsed;
  } catch (error) {
    findings.push(
      finding(
        'invalid_toml',
        'error',
        'automation.toml',
        'automation.toml is not valid TOML.',
      ),
    );
    return {
      ok: false,
      config: null,
      findings,
      source,
      sourceHash,
      compatible: false,
      importState: 'disabled',
    };
  }

  for (const key of REQUIRED_KEYS) {
    if (!(key in table)) {
      findings.push(finding('missing_field', 'error', key, `Missing required field: ${key}.`));
    }
  }
  for (const key of Object.keys(table)) {
    if (!KNOWN_KEYS.has(key)) {
      findings.push(
        finding('unknown_field', 'error', key, `Unknown top-level field is not allowed: ${key}.`),
      );
    }
  }

  const schemaVersion = table.schema_version;
  if (!Number.isInteger(schemaVersion)) {
    findings.push(
      finding('invalid_schema_version', 'error', 'schema_version', 'schema_version must be an integer.'),
    );
  } else if (schemaVersion !== AUTOMATION_SCHEMA_VERSION) {
    findings.push(
      finding(
        'unsupported_schema',
        'error',
        'schema_version',
        `Only schema_version ${AUTOMATION_SCHEMA_VERSION} is supported.`,
      ),
    );
  }

  const name = stringValue(table, 'name', findings);
  const description = stringValue(table, 'description', findings);
  const platform = stringValue(table, 'platform', findings);
  const format = stringValue(table, 'format', findings);
  const version = stringValue(table, 'version', findings);
  const scheduleType = stringValue(table, 'schedule_type', findings);
  const timezone = stringValue(table, 'timezone', findings);
  const trigger = stringValue(table, 'trigger', findings);
  const requiredPermissions = stringArray(table, 'required_permissions', findings) || [];
  const requiredConnectors = stringArray(table, 'required_connectors', findings) || [];
  const workspaceRequired = booleanValue(table, 'workspace_required', findings);
  const deliveryType = stringValue(table, 'delivery_type', findings);
  const testedOn = stringArray(table, 'tested_on', findings) || [];
  const tags = stringArray(table, 'tags', findings) || [];
  const license = stringValue(table, 'license', findings);
  const enabled = booleanValue(table, 'enabled', findings);

  if (format && format !== 'automation') {
    findings.push(
      finding('invalid_format', 'error', 'format', 'format must be "automation".'),
    );
  }
  if (version && !SEMVER.test(version)) {
    findings.push(
      finding('invalid_version', 'error', 'version', 'version must use semantic versioning.'),
    );
  }
  if (scheduleType && !SCHEDULE_TYPES.has(scheduleType)) {
    findings.push(
      finding(
        'invalid_schedule_type',
        'error',
        'schedule_type',
        `schedule_type must be one of: ${[...SCHEDULE_TYPES].join(', ')}.`,
      ),
    );
  }
  if (deliveryType && !DELIVERY_TYPES.has(deliveryType)) {
    findings.push(
      finding(
        'invalid_delivery_type',
        'error',
        'delivery_type',
        `delivery_type must be one of: ${[...DELIVERY_TYPES].join(', ')}.`,
      ),
    );
  }
  if (enabled) {
    findings.push(
      finding(
        'enabled_public_config',
        'error',
        'enabled',
        'Published Automations must be disabled until the importing user confirms activation.',
      ),
    );
  }
  if (deliveryType && deliveryType !== 'none') {
    findings.push(
      finding(
        'external_delivery',
        'warning',
        'delivery_type',
        'External delivery requires explicit confirmation during import.',
      ),
    );
  }
  if (platform && platform.toLowerCase() !== 'codex') {
    findings.push(
      finding(
        'runtime_compatibility',
        'warning',
        'platform',
        `This package targets ${platform}; the local Codex runtime may not be compatible.`,
      ),
    );
  }

  const sensitiveMatches = [...raw.matchAll(SENSITIVE_ASSIGNMENT)];
  for (const match of sensitiveMatches) {
    const value = match[1].trim();
    if (!PLACEHOLDER.test(value)) {
      findings.push(
        finding(
          'embedded_secret',
          'error',
          'automation.toml',
          'A credential-like value is embedded in the public TOML.',
        ),
      );
    }
  }
  scanTable(table, findings);

  const config: AutomationConfig = {
    schema_version:
      typeof schemaVersion === 'number' && Number.isInteger(schemaVersion) ? schemaVersion : 0,
    name,
    description,
    platform,
    format: 'automation',
    version,
    schedule_type: scheduleType,
    timezone,
    trigger,
    required_permissions: requiredPermissions,
    required_connectors: requiredConnectors,
    workspace_required: workspaceRequired,
    delivery_type: deliveryType,
    tested_on: testedOn,
    tags,
    license,
    enabled,
    required_secrets: stringArray(table, 'required_secrets', findings, true),
    related_prompts: stringArray(table, 'related_prompts', findings, true),
    related_skills: stringArray(table, 'related_skills', findings, true),
    related_mcps: stringArray(table, 'related_mcps', findings, true),
    notes: typeof table.notes === 'string' ? table.notes.trim() : undefined,
  };
  const uniqueFindings = deduplicateFindings(findings);
  const compatible =
    config.schema_version === AUTOMATION_SCHEMA_VERSION &&
    config.platform.toLowerCase() === 'codex';
  return {
    ok: !uniqueFindings.some((item) => item.severity === 'error'),
    config,
    findings: uniqueFindings,
    source,
    sourceHash,
    compatible,
    importState: 'disabled',
  };
}

export function buildDisabledAutomationBundle(
  preflight: AutomationPreflight,
  options: AutomationBundleOptions = {},
): string {
  if (!preflight.ok || !preflight.config) {
    throw new Error('A valid Automation preflight is required before generating a bundle.');
  }
  if (
    preflight.findings.some((item) => item.severity === 'warning') &&
    !options.acknowledgeWarnings
  ) {
    throw new Error('Automation warnings must be acknowledged before generating a bundle.');
  }
  const config = { ...preflight.config, enabled: false };
  return [
    '# Generated by NyankoFace after schema and security preflight.',
    '# Review permissions, schedule, connectors, workspace scope, and delivery before enabling.',
    stringify(config).trimEnd(),
    '',
  ].join('\n');
}
