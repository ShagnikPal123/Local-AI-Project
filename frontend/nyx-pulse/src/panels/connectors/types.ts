/** Shapes the Connectors routes return (routes_connectors.py, connectors/catalog.py). */

export interface ConnectorField {
  key: string;
  label: string;
  secret: boolean;
  required: boolean;
  help_url?: string;
  kind?: string;
  placeholder?: string;
  choices?: string[];
  default?: string;
}

export interface ConnectorAction {
  id: string;
  description?: string;
  write?: boolean;
  method?: string;
  path?: string;
  params?: Record<string, string>;
}

export type ConnectorKind =
  | "rest" | "mcp" | "oauth_google" | "oauth_microsoft" | "builtin" | "website" | "webhook" | "provider" | "model";

export interface Connector {
  id: string;
  name: string;
  category: string;
  kind: ConnectorKind;
  description: string;
  keywords: string[];
  base_url?: string;
  mcp_url?: string;
  fields: ConnectorField[];
  can: string[];
  writes: boolean;
  docs_url?: string;
  help_url?: string;
  enable_url?: string;
  google_product?: string;
  microsoft_product?: string;
  color: string;
  mark: string;
  popular: number;
  note?: string;
  tools?: string[];
  template?: boolean;
  paid?: boolean;
  origin: "catalog" | "custom";
  action_count: number;
  actions: ConnectorAction[];
  connected: boolean;
  accounts: string[];
  mail_accounts?: string[];
  saved: Record<string, string>;
  connected_at: number | null;
  how: string;
}

export interface Category { id: string; label: string }

export interface UseSettings { auto: boolean; confirm_writes: boolean; max_per_turn: number }

export interface CatalogResponse {
  categories: Category[];
  connectors: Connector[];
  settings: UseSettings;
  connected: number;
  total: number;
}

/** A machine connector from the registry (`GET /api/connectors`): files, apps, system control… */
export interface BuiltinConnector {
  name: string;
  description: string;
  permissions: string[];
  is_offline: boolean;
  requires_auth: boolean;
  is_write: boolean;
  risk_level: string;
  available: boolean;
}

export interface DraftField extends ConnectorField {
  value?: string;
  filled: boolean;
  masked?: string;
}

export interface Draft {
  draft_id: string;
  catalog_id: string;
  id: string;
  name: string;
  kind: string;
  description: string;
  help_url: string;
  source: string;
  fields: DraftField[];
  missing: string[];
  ready: boolean;
  open: string;
  blocked: string;
  suggest: string;
  base_url: string;
  message: string;
}

export type Note = { ok: boolean; text: string } | null;
