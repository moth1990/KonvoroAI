/**
 * Typed API client. Types come from `make gen-client` (FastAPI's OpenAPI -> schema.ts); never edit them by hand.
 *
 * - Every request carries the bearer token.
 * - A 401 on any route but login clears the token and sends the user to the login screen.
 * - Errors arrive as `{error: {code, message}}`: `code` is for code, `message` is Hebrew for the user.
 */
import createClient, { type Middleware } from "openapi-fetch";

import type { components, paths } from "./schema";
import { clearToken, getToken, setToken } from "./token";

export type Schemas = components["schemas"];
export type Me = Schemas["MeOut"];
export type Quota = Schemas["QuotaOut"];
export type TenantSettings = Schemas["SettingsOut"];
export type QuoteListItem = Schemas["QuoteListItem"];
export type HomeSummary = Schemas["HomeSummaryOut"];
export type Progress = Schemas["ProgressOut"];
export type Revisable = Schemas["RevisableOut"];
export type UploadedFile = Schemas["UploadedFileOut"];
export type Quote = Schemas["QuoteOut"];
export type QuoteLine = Schemas["LineOut"];
export type Finding = Schemas["FindingOut"];
export type QuotePage = Schemas["PageOut"];
export type Audit = Schemas["AuditOut"];
export type AuditDifference = Schemas["AuditDifferenceOut"];
export type AuditLine = Schemas["AuditLineOut"];
export type RejectReason = NonNullable<Schemas["AuditDecisionIn"]["reject_reason"]>;

const FALLBACK_MESSAGE = "משהו השתבש אצלנו. נסו שוב בעוד רגע";
const LOGIN_PATH = "/auth/login";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>[];

  constructor(status: number, code: string, message: string, details: Record<string, unknown>[] = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

/** The prototype shows login whenever the user is not signed in (konboro-app.html `vLogin`). The app's router
 * replaces this with a navigation that keeps the page to return to (`AuthBridge`). */
let onUnauthorized: () => void = () => {
  window.location.assign("/login");
};

export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

const auth: Middleware = {
  onRequest({ request }) {
    const token = getToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
  onResponse({ request, response }) {
    if (response.status === 401 && !new URL(request.url).pathname.endsWith(LOGIN_PATH)) {
      clearToken();
      onUnauthorized();
    }
    return response;
  },
};

/** Where the API is. The drawing viewer loads its tiles from here too, outside openapi-fetch (S11). */
export const API_BASE: string = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export function createApiClient(options: { baseUrl?: string; fetch?: typeof fetch } = {}) {
  const client = createClient<paths>({
    baseUrl: options.baseUrl ?? API_BASE,
    fetch: options.fetch,
  });
  client.use(auth);
  return client;
}

export const api = createApiClient();

/** openapi-fetch returns `{data}` or `{error}`. This returns the data or throws an ApiError. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error === undefined && result.response.ok) return result.data as T;
  const body = (result.error ?? {}) as {
    error?: { code?: string; message?: string; details?: Record<string, unknown>[] | null };
  };
  throw new ApiError(
    result.response.status,
    body.error?.code ?? "internal_error",
    body.error?.message ?? FALLBACK_MESSAGE,
    body.error?.details ?? [],
  );
}

export async function login(email: string, password: string, client = api): Promise<void> {
  const data = unwrap(await client.POST("/auth/login", { body: { email, password } }));
  setToken(data.access_token);
}

export async function logout(client = api): Promise<void> {
  try {
    await client.POST("/auth/logout");
  } finally {
    clearToken();
  }
}

export async function fetchMe(client = api): Promise<Me> {
  return unwrap(await client.GET("/me"));
}

/** Always succeeds (202), whether or not the email is registered, so nothing is revealed. */
export async function requestPasswordReset(email: string, client = api): Promise<void> {
  unwrap(await client.POST("/auth/password-reset", { body: { email } }));
}

export async function fetchQuotes(limit: number, client = api): Promise<QuoteListItem[]> {
  return unwrap(await client.GET("/quotes", { params: { query: { limit } } })).items;
}

export async function fetchHomeSummary(client = api): Promise<HomeSummary> {
  return unwrap(await client.GET("/home/summary"));
}

export interface UploadForm {
  files: File[];
  customer?: string;
  project?: string;
  revisionOf?: string;
}

/** POST /drawings as multipart. A rejected upload throws ApiError("upload_rejected") with one detail per file. */
export async function uploadDrawing(form: UploadForm, client = api) {
  const data = new FormData();
  for (const f of form.files) data.append("files", f, f.name);
  if (form.revisionOf) data.append("revision_of", form.revisionOf);
  else {
    if (form.customer?.trim()) data.append("customer", form.customer.trim());
    if (form.project?.trim()) data.append("project", form.project.trim());
  }
  return unwrap(
    await client.POST("/drawings", {
      // openapi-fetch types the multipart body as its fields; the FormData built above is what goes out.
      body: data as unknown as Schemas["Body_upload_drawings_post"],
      bodySerializer: (body) => body as unknown as FormData,
    }),
  );
}

/** `shownLeft`: the time left the live run step shows now, so the next one rises at most a fifth (01 §4.6). */
export async function fetchProgress(drawingId: string, shownLeft?: number | null, client = api): Promise<Progress> {
  const query = shownLeft != null ? { shown_left: shownLeft } : undefined;
  return unwrap(
    await client.GET("/drawings/{drawing_id}/progress", { params: { path: { drawing_id: drawingId }, query } }),
  );
}

export type Live = Schemas["LiveOut"];
export type Estimate = Schemas["EstimateOut"];
export type FileCheck = Schemas["CheckOut"];

/** The start bar's check (01 §4.6 item 4, behind `live_run`): pages, rejections and the rough estimate, nothing stored. */
export async function checkFiles(files: File[], purpose: "quote" | "audit" = "quote", client = api) {
  const data = new FormData();
  for (const f of files) data.append("files", f, f.name);
  data.append("purpose", purpose);
  return unwrap(
    await client.POST("/drawings/check", {
      body: data as unknown as Schemas["Body_check_drawings_check_post"],
      bodySerializer: (body) => body as unknown as FormData,
    }),
  );
}

export async function cancelDrawing(drawingId: string, client = api): Promise<Progress> {
  return unwrap(await client.POST("/drawings/{drawing_id}/cancel", { params: { path: { drawing_id: drawingId } } }));
}

export async function confirmDrawing(drawingId: string, client = api): Promise<Progress> {
  return unwrap(await client.POST("/drawings/{drawing_id}/confirm", { params: { path: { drawing_id: drawingId } } }));
}

export type PageKind = Schemas["PageKindIn"]["page_kind"];
export type BomRole = Schemas["BomColumnRoleIn"]["role"];

/** A BOM spreadsheet's column roles (01 §5.8, behind `bom_column_mapping`). */
export async function setBomColumns(
  drawingId: string,
  pageId: string,
  columns: { index: number; role: BomRole }[],
  client = api,
): Promise<Progress> {
  return unwrap(
    await client.PUT("/drawings/{drawing_id}/pages/{page_id}/bom-columns", {
      params: { path: { drawing_id: drawingId, page_id: pageId } },
      body: { columns },
    }),
  );
}

export async function changePageKind(
  drawingId: string,
  pageId: string,
  pageKind: PageKind,
  client = api,
): Promise<Progress> {
  return unwrap(
    await client.PATCH("/drawings/{drawing_id}/pages/{page_id}", {
      params: { path: { drawing_id: drawingId, page_id: pageId } },
      body: { page_kind: pageKind },
    }),
  );
}

export async function fetchRevisable(client = api): Promise<Revisable[]> {
  return unwrap(await client.GET("/drawings/revisable"));
}

/** The review screen's quote (09 §4). 404 when it is another tenant's or does not exist. */
export async function fetchQuote(quoteId: string, client = api): Promise<Quote> {
  return unwrap(await client.GET("/quotes/{quote_id}", { params: { path: { quote_id: quoteId } } }));
}

// --- the quote's documents (13 §4.1, `export_doc`; S26) --------------------------------------------------------------

export type QuoteVersion = Schemas["VersionOut"];
export type CustomerDocument = Schemas["DocumentOut"];
export type DocumentSettings = Schemas["DocumentSettingsOut"];
export type DocumentSettingsIn = Schemas["DocumentSettingsIn"];
export type ExportKind = "pdf" | "xlsx";

export async function fetchVersions(quoteId: string, client = api): Promise<QuoteVersion[]> {
  return unwrap(await client.GET("/quotes/{quote_id}/versions", { params: { path: { quote_id: quoteId } } }));
}

/** The customer document of one version, as the PDF prints it: the export modal's preview. */
export async function fetchCustomerDocument(quoteId: string, version: number, client = api): Promise<CustomerDocument> {
  return unwrap(
    await client.GET("/quotes/{quote_id}/versions/{version}/document", {
      params: { path: { quote_id: quoteId, version } },
    }),
  );
}

/** The file's name from `Content-Disposition` (its UTF-8 form), or null. */
export function attachmentName(header: string | null): string | null {
  const m = /filename\*=UTF-8''([^;]+)/i.exec(header ?? "");
  if (!m?.[1]) return null;
  try {
    return decodeURIComponent(m[1]);
  } catch {
    return null;
  }
}

/** The customer PDF or the internal Excel of one version, with the name the server gave it. */
export async function fetchExport(
  quoteId: string,
  version: number,
  kind: ExportKind,
  client = api,
): Promise<{ blob: Blob; name: string | null }> {
  const params = { path: { quote_id: quoteId, version } };
  const result =
    kind === "pdf"
      ? await client.GET("/quotes/{quote_id}/versions/{version}/export.pdf", { params, parseAs: "blob" })
      : await client.GET("/quotes/{quote_id}/versions/{version}/export.xlsx", { params, parseAs: "blob" });
  const blob = unwrap(result as { data?: Blob; error?: unknown; response: Response });
  return { blob, name: attachmentName(result.response.headers.get("Content-Disposition")) };
}

export async function fetchDocumentSettings(client = api): Promise<DocumentSettings> {
  return unwrap(await client.GET("/settings/document"));
}

export async function saveDocumentSettings(body: DocumentSettingsIn, client = api): Promise<DocumentSettings> {
  return unwrap(await client.PUT("/settings/document", { body }));
}

export async function uploadLogo(file: File, client = api): Promise<DocumentSettings> {
  const data = new FormData();
  data.append("file", file, file.name);
  return unwrap(
    await client.PUT("/settings/document/logo", {
      body: data as unknown as Schemas["Body_put_logo_settings_document_logo_put"],
      bodySerializer: (body) => body as unknown as FormData,
    }),
  );
}

export async function deleteLogo(client = api): Promise<DocumentSettings> {
  return unwrap(await client.DELETE("/settings/document/logo"));
}

export type UnresolvedSpot = Schemas["UnresolvedSpotOut"];

/** 13 §4.4: the "לא פוענח" layer of the quote's current version. Behind `unresolved_overlay` (404 when off). */
export async function fetchUnresolved(quoteId: string, client = api): Promise<UnresolvedSpot[]> {
  return unwrap(await client.GET("/quotes/{quote_id}/unresolved", { params: { path: { quote_id: quoteId } } })).spots;
}

// --- review actions (09 §7, S23) -------------------------------------------------------------------------------------

export type ActionResult = Schemas["ActionOut"];
export type Recalculation = Schemas["RecalculationOut"];
export type DismissReason = Schemas["DismissIn"]["reason"];

/**
 * One action of the review screen. Every one answers with the quote as it now is, the toast's text and the event
 * "בטל" takes back. A sent version answers 409 to every one (07 §7.7).
 */
export type LineAction =
  | { kind: "approve" }
  | { kind: "delete" }
  | { kind: "qty"; qty: string }
  | { kind: "alternative"; index: number; designators?: string[] }
  | { kind: "price"; unit_price: string; scope: "quote" | "catalog" }
  | { kind: "price-entry"; unit_price: string; save: boolean }
  | { kind: "cost"; unit_cost: string; supplier: string | null }
  | { kind: "list-price" }
  | { kind: "supplier"; supplier_price_id: string }
  | { kind: "preferred" }
  | { kind: "attribute"; attribute: EditableAttribute; value: string }
  | { kind: "resolve"; ref: string; designators?: string[] }
  | { kind: "brand-discount"; discount_pct: string }
  | { kind: "new-product"; product: NewProduct };

/** 09 §7.16 (S27b): "מוצר חדש" from a waiting line. */
export type NewProduct = Schemas["NewProductIn"];
export type NewProductForm = Schemas["NewProductFormOut"];

export type EditableAttribute = Schemas["AttributeIn"]["attribute"];
export type ProductChoice = Schemas["ProductChoiceOut"];

export async function lineAction(
  quoteId: string,
  lineId: string,
  action: LineAction,
  client = api,
): Promise<ActionResult> {
  const path = { quote_id: quoteId, line_id: lineId };
  switch (action.kind) {
    case "approve":
      return unwrap(await client.POST("/quotes/{quote_id}/lines/{line_id}/approve", { params: { path } }));
    case "delete":
      return unwrap(await client.DELETE("/quotes/{quote_id}/lines/{line_id}", { params: { path } }));
    case "qty":
      return unwrap(
        await client.POST("/quotes/{quote_id}/lines/{line_id}/qty", { params: { path }, body: { qty: action.qty } }),
      );
    case "alternative":
      return unwrap(
        await client.POST("/quotes/{quote_id}/lines/{line_id}/alternative", {
          params: { path },
          body: { index: action.index, ...(action.designators?.length ? { designators: action.designators } : {}) },
        }),
      );
    case "price":
      return unwrap(
        await client.POST("/quotes/{quote_id}/lines/{line_id}/price", {
          params: { path },
          body: { unit_price: action.unit_price, scope: action.scope },
        }),
      );
    case "price-entry":
      return unwrap(
        await client.POST("/quotes/{quote_id}/lines/{line_id}/price-entry", {
          params: { path },
          body: { unit_price: action.unit_price, save: action.save },
        }),
      );
    case "cost":
      return unwrap(
        await client.POST("/quotes/{quote_id}/lines/{line_id}/cost", {
          params: { path },
          body: { unit_cost: action.unit_cost, supplier: action.supplier },
        }),
      );
    case "list-price":
      return unwrap(await client.POST("/quotes/{quote_id}/lines/{line_id}/list-price", { params: { path } }));
    case "supplier":
      return unwrap(
        await client.POST("/quotes/{quote_id}/lines/{line_id}/supplier", {
          params: { path },
          body: { supplier_price_id: action.supplier_price_id },
        }),
      );
    case "preferred":
      return unwrap(await client.POST("/quotes/{quote_id}/lines/{line_id}/supplier/preferred", { params: { path } }));
    case "attribute":
      return unwrap(
        await client.POST("/quotes/{quote_id}/lines/{line_id}/attribute", {
          params: { path },
          body: { attribute: action.attribute, value: action.value },
        }),
      );
    case "resolve":
      return unwrap(
        await client.POST("/quotes/{quote_id}/lines/{line_id}/resolve", {
          params: { path },
          body: { ref: action.ref, ...(action.designators?.length ? { designators: action.designators } : {}) },
        }),
      );
    case "brand-discount":
      return unwrap(
        await client.POST("/quotes/{quote_id}/lines/{line_id}/brand-discount", {
          params: { path },
          body: { discount_pct: action.discount_pct },
        }),
      );
    case "new-product":
      return unwrap(
        await client.POST("/quotes/{quote_id}/lines/{line_id}/new-product", { params: { path }, body: action.product }),
      );
  }
}

/** 09 §7.16 (S27b): what "מוצר חדש" opens with: the family, its attributes and what was read. */
export async function newProductForm(quoteId: string, lineId: string, client = api): Promise<NewProductForm> {
  return unwrap(
    await client.GET("/quotes/{quote_id}/lines/{line_id}/new-product", {
      params: { path: { quote_id: quoteId, line_id: lineId } },
    }),
  );
}

/** The name the product would get, built by the server in the app's wording as the form is filled. */
export async function newProductName(
  quoteId: string,
  lineId: string,
  values: Schemas["NewProductNameIn"],
  client = api,
): Promise<string> {
  const out = unwrap(
    await client.POST("/quotes/{quote_id}/lines/{line_id}/new-product/name", {
      params: { path: { quote_id: quoteId, line_id: lineId } },
      body: values,
    }),
  );
  return out.name;
}

// --- the product picker (09 §6.4, §6.6, §7.8; S23b) ------------------------------------------------------------------

/** The master catalog and the factory's products, priced first; `family` narrows to the line's. */
export async function searchProducts(
  quoteId: string,
  q: string,
  family?: string | null,
  client = api,
): Promise<ProductChoice[]> {
  return unwrap(
    await client.GET("/quotes/{quote_id}/products", {
      params: { path: { quote_id: quoteId }, query: { q: q || undefined, family: family || undefined } },
    }),
  );
}

/** Up to three products for a missing line, by what was read beside it. */
export async function missingCandidates(quoteId: string, lineId: string, client = api): Promise<ProductChoice[]> {
  return unwrap(
    await client.GET("/quotes/{quote_id}/lines/{line_id}/candidates", {
      params: { path: { quote_id: quoteId, line_id: lineId } },
    }),
  );
}

/** 09 §6.6: a rectangle on a page, in PDF points, and the product for it: a manual line there. */
export async function markComponent(
  quoteId: string,
  mark: { page_id: string; bbox: number[]; ref: string; panel_id?: string | null },
  client = api,
): Promise<ActionResult> {
  return unwrap(await client.POST("/quotes/{quote_id}/marks", { params: { path: { quote_id: quoteId } }, body: mark }));
}

/** 09 §6.3 "החזר": derived lines removed from the quote, back. */
export async function restoreLines(quoteId: string, lineIds: string[], client = api): Promise<ActionResult> {
  return unwrap(
    await client.POST("/quotes/{quote_id}/lines/restore", {
      params: { path: { quote_id: quoteId } },
      body: { line_ids: lineIds },
    }),
  );
}

/** 09 §7.7: dismissed with a reason; "אחר" needs its text. */
export async function dismissFinding(
  quoteId: string,
  findingId: string,
  reason: DismissReason,
  text?: string,
  client = api,
): Promise<ActionResult> {
  return unwrap(
    await client.POST("/quotes/{quote_id}/findings/{finding_id}/dismiss", {
      params: { path: { quote_id: quoteId, finding_id: findingId } },
      body: { reason, text: text ?? null },
    }),
  );
}

/** 09 §7.11: takes an action back, by its event. */
export async function undoAction(quoteId: string, eventId: string, client = api): Promise<ActionResult> {
  return unwrap(
    await client.POST("/quotes/{quote_id}/undo/{event_id}", {
      params: { path: { quote_id: quoteId, event_id: eventId } },
    }),
  );
}

/** 09 §7.12: the version locked; the only action with no undo. */
export async function sendQuote(quoteId: string, client = api): Promise<Quote> {
  return unwrap(await client.POST("/quotes/{quote_id}/send", { params: { path: { quote_id: quoteId } } }));
}

/** "פתח גרסה N+1": a draft copy of the sent version. */
export async function openNextVersion(quoteId: string, client = api): Promise<Quote> {
  return unwrap(await client.POST("/quotes/{quote_id}/versions", { params: { path: { quote_id: quoteId } } }));
}

/** 07 §7.2.3: what "חישוב מחדש" would change. Nothing is written. */
export async function previewRecalculation(quoteId: string, client = api): Promise<Recalculation> {
  return unwrap(await client.GET("/quotes/{quote_id}/recalculation", { params: { path: { quote_id: quoteId } } }));
}

export async function recalculateQuote(quoteId: string, client = api): Promise<Quote> {
  return unwrap(await client.POST("/quotes/{quote_id}/recalculation", { params: { path: { quote_id: quoteId } } }));
}

/** The audit of an existing quote (11 §6, S15). 404 when it is another tenant's, or `quote_audit` is off. */
export async function fetchAudit(auditId: string, client = api): Promise<Audit> {
  return unwrap(await client.GET("/audits/{audit_id}", { params: { path: { audit_id: auditId } } }));
}

/** POST /audits as multipart: the drawing's files and the existing quote (11 §4). Rejected like an upload. */
export async function uploadAudit(form: { files: File[]; quote: File; project?: string }, client = api) {
  const data = new FormData();
  for (const f of form.files) data.append("files", f, f.name);
  data.append("quote", form.quote, form.quote.name);
  if (form.project?.trim()) data.append("project", form.project.trim());
  return unwrap(
    await client.POST("/audits", {
      body: data as unknown as Schemas["Body_upload_audit_audits_post"],
      bodySerializer: (body) => body as unknown as FormData,
    }),
  );
}

/** 11 §7: "נכון, זה הבדל" (`confirmed`), "לא נכון" with a reason (`rejected`), or back to `open`. */
export async function decideDifference(
  auditId: string,
  diffId: string,
  decision: { status: AuditDifference["status"]; reject_reason?: RejectReason; note?: string },
  client = api,
): Promise<AuditDifference> {
  return unwrap(
    await client.PATCH("/audits/{audit_id}/differences/{diff_id}", {
      params: { path: { audit_id: auditId, diff_id: diffId } },
      body: decision,
    }),
  );
}

/** 11 §8: the quote's lines and the confirmed differences as a quote in the system; asked again, the same one. */
export async function createCorrectedQuote(auditId: string, client = api): Promise<string> {
  return unwrap(await client.POST("/audits/{audit_id}/corrected-quote", { params: { path: { audit_id: auditId } } }))
    .quote_id;
}

// --- price list (07 §7.2–7.3, S18; the screen is S19) -----------------------------------------------------------------

export type Product = Schemas["ProductOut"];
export type ProductBody = Schemas["ProductIn"];
export type CostCheck = Schemas["CostCheckOut"];
export type MarginRule = Schemas["MarginRuleOut"];
export type BrandDiscount = Schemas["BrandDiscountOut"];
export type Supplier = Schemas["SupplierOut"];

/** The whole price list: the screen searches and filters it in memory, as the prototype does on every key. */
export async function fetchProducts(client = api): Promise<Product[]> {
  return unwrap(await client.GET("/price-list/products"));
}

/** One product with its history and the drafts that use it. */
export async function fetchProduct(productId: string, client = api): Promise<Product> {
  return unwrap(await client.GET("/price-list/products/{product_id}", { params: { path: { product_id: productId } } }));
}

export async function createProduct(body: ProductBody, client = api): Promise<Product> {
  return unwrap(await client.POST("/price-list/products", { body }));
}

/** Only the fields sent change; `suppliers`, when sent, is the whole list. */
export async function updateProduct(productId: string, body: Schemas["ProductPatch"], client = api): Promise<Product> {
  return unwrap(
    await client.PATCH("/price-list/products/{product_id}", { params: { path: { product_id: productId } }, body }),
  );
}

/** 10 §8 on a cost that is not saved yet (S19 decision 4). Nothing is written. */
export async function checkCost(body: Schemas["CostCheckIn"], client = api): Promise<CostCheck> {
  return unwrap(await client.POST("/price-list/products/check-cost", { body }));
}

export async function fetchSuppliers(client = api): Promise<Supplier[]> {
  return unwrap(await client.GET("/price-list/suppliers"));
}

export async function fetchMarginRules(client = api): Promise<MarginRule[]> {
  return unwrap(await client.GET("/price-list/margin-rules"));
}

export async function fetchBrands(client = api): Promise<string[]> {
  return unwrap(await client.GET("/price-list/brands"));
}

export async function fetchBrandDiscounts(client = api): Promise<BrandDiscount[]> {
  return unwrap(await client.GET("/price-list/brand-discounts"));
}

/** "הנחת מותג גורפת": the brand's list price less `discountPct` ("0.38"). */
export async function setBrandDiscount(brand: string, discountPct: string, client = api): Promise<BrandDiscount> {
  return unwrap(
    await client.PUT("/price-list/brand-discounts/{brand}", {
      params: { path: { brand } },
      body: { discount_pct: discountPct },
    }),
  );
}

export async function deleteBrandDiscount(brand: string, client = api): Promise<void> {
  unwrap(await client.DELETE("/price-list/brand-discounts/{brand}", { params: { path: { brand } } }));
}

export async function fetchSettings(client = api): Promise<TenantSettings> {
  return unwrap(await client.GET("/settings"));
}

// --- onboarding, settings and the approval queue (S24: 10 §5.1, §9.1; 00 §14.2) ---------------------------------------

export type Onboarding = Schemas["OnboardingOut"];
export type OnboardingAnswer = Schemas["OnboardingIn"];
export type SettingsPatch = Schemas["SettingsPatch"];
export type Candidate = Schemas["CandidateOut"];
export type CandidateList = Schemas["CandidateList"];

export async function fetchOnboarding(client = api): Promise<Onboarding> {
  return unwrap(await client.GET("/onboarding"));
}

/** The two questions and the data terms, in one step. Until then uploads answer 409 `data_terms_required`. */
export async function answerOnboarding(body: OnboardingAnswer, client = api): Promise<Onboarding> {
  return unwrap(await client.POST("/onboarding", { body }));
}

/** Only the fields sent change. Flags are not here: they are read-only (S03 decision). */
export async function patchSettings(body: SettingsPatch, client = api): Promise<TenantSettings> {
  return unwrap(await client.PATCH("/settings", { body }));
}

export async function fetchCandidates(client = api): Promise<CandidateList> {
  return unwrap(await client.GET("/knowledge-candidates"));
}

/** "אשר לשכבה המשותפת": the only way a candidate reaches the shared layer (00 §14.2). */
export async function approveCandidate(candidateId: string, client = api): Promise<Candidate> {
  return unwrap(
    await client.POST("/knowledge-candidates/{candidate_id}/approve", {
      params: { path: { candidate_id: candidateId } },
    }),
  );
}

/** "דחה": it stays with the factory. */
export async function rejectCandidate(
  candidateId: string,
  reason: string | null = null,
  client = api,
): Promise<Candidate> {
  return unwrap(
    await client.POST("/knowledge-candidates/{candidate_id}/reject", {
      params: { path: { candidate_id: candidateId } },
      body: { reason },
    }),
  );
}

// --- the chat (08, S25) ----------------------------------------------------------------------------------------------

export type Chat = Schemas["ChatOut"];
export type ChatMessage = Schemas["ChatMessageOut"];
export type ChatBlock = Schemas["ChatBlockOut"];
export type ChatProposal = Schemas["ChatProposalOut"];
export type ChatTurn = Schemas["ChatTurnOut"];
export type ChatApply = Schemas["ChatApplyOut"];
export type ChatUiContext = Schemas["ChatUiContextIn"];
export type ChatMoney = Schemas["ChatMoneyOut"];
export type ChatInstance = Schemas["ChatInstanceOut"];

export async function fetchChat(quoteId: string, client = api): Promise<Chat> {
  return unwrap(await client.GET("/quotes/{quote_id}/chat", { params: { path: { quote_id: quoteId } } }));
}

/** One turn (08 §4–§8): the answer's blocks, with the amounts of the money references they use. */
export async function sendChatMessage(
  quoteId: string,
  message: string,
  uiContext: ChatUiContext,
  client = api,
): Promise<ChatTurn> {
  return unwrap(
    await client.POST("/quotes/{quote_id}/chat/messages", {
      params: { path: { quote_id: quoteId } },
      body: { message, ui_context: uiContext },
    }),
  );
}

/** "שיחה חדשה": the active conversation is closed and kept read only. */
export async function newChat(quoteId: string, client = api): Promise<Chat> {
  return unwrap(await client.POST("/quotes/{quote_id}/chat/new", { params: { path: { quote_id: quoteId } } }));
}

/** 08 §7.5: the estimator's approval. The answer has the quote as it now is and the event "בטל" undoes. */
/** 08 §7.5; `remember` (08 §7.4): "customer" or "tenant" writes the match memory too, when the card offers it. */
export async function applyProposal(
  proposalId: string,
  remember: "quote_only" | "customer" | "tenant" = "quote_only",
  client = api,
): Promise<ChatApply> {
  return unwrap(
    await client.POST("/chat/proposals/{proposal_id}/apply", {
      params: { path: { proposal_id: proposalId } },
      body: { remember },
    }),
  );
}

export async function dismissProposal(proposalId: string, client = api): Promise<ChatProposal> {
  return unwrap(
    await client.POST("/chat/proposals/{proposal_id}/dismiss", { params: { path: { proposal_id: proposalId } } }),
  );
}

// --- the chat quote builder (13 §4.2, S27) ---------------------------------------------------------------------------

export type Build = Schemas["BuildOut"];
export type BuildMessage = Schemas["BuildMessageOut"];

/** The first message starts the build; the quote exists from its first line (S27 decision 2). */
export async function startBuild(text: string, client = api): Promise<Build> {
  return unwrap(await client.POST("/builds", { body: { text } }));
}

export async function fetchBuild(drawingId: string, client = api): Promise<Build> {
  return unwrap(await client.GET("/builds/{drawing_id}", { params: { path: { drawing_id: drawingId } } }));
}

export async function sendBuildMessage(drawingId: string, text: string, client = api): Promise<Build> {
  return unwrap(
    await client.POST("/builds/{drawing_id}/messages", { params: { path: { drawing_id: drawingId } }, body: { text } }),
  );
}

/** "הוסף" (apply) or "תקן" (dismiss) on a recording's card (S27 decision 1). */
export async function settleBuildMessage(
  drawingId: string,
  messageId: string,
  how: "apply" | "dismiss",
  client = api,
): Promise<Build> {
  const params = { path: { drawing_id: drawingId, message_id: messageId } };
  return unwrap(
    how === "apply"
      ? await client.POST("/builds/{drawing_id}/messages/{message_id}/apply", { params })
      : await client.POST("/builds/{drawing_id}/messages/{message_id}/dismiss", { params }),
  );
}

export async function undoBuild(drawingId: string, client = api): Promise<Build> {
  return unwrap(await client.POST("/builds/{drawing_id}/undo", { params: { path: { drawing_id: drawingId } } }));
}

// --- the chat home's routing (13 §4.3, S27) --------------------------------------------------------------------------

export type HomeRoute = Schemas["HomeRouteOut"];
export type HomeChoice = Schemas["HomeChoiceOut"];

export async function routeHomeRequest(text: string, client = api): Promise<HomeRoute> {
  return unwrap(await client.POST("/home/route", { body: { text } }));
}

/** A recording, transcribed on the server and never stored; what was heard waits for "הוסף" (S27 decision 1). */
export async function sendBuildVoice(
  drawingId: string | null,
  audio: Blob,
  seconds: number,
  client = api,
): Promise<Build> {
  const data = new FormData();
  const ext = audio.type.includes("mp4") ? "m4a" : audio.type.includes("ogg") ? "ogg" : "webm";
  data.append("recording", audio, `recording.${ext}`);
  data.append("seconds", seconds.toFixed(1));
  const bodySerializer = (body: unknown) => body as FormData;
  if (!drawingId)
    return unwrap(
      await client.POST("/builds/voice", {
        body: data as unknown as Schemas["Body_start_build_by_voice_builds_voice_post"],
        bodySerializer,
      }),
    );
  return unwrap(
    await client.POST("/builds/{drawing_id}/voice", {
      params: { path: { drawing_id: drawingId } },
      body: data as unknown as Schemas["Body_send_build_voice_builds__drawing_id__voice_post"],
      bodySerializer,
    }),
  );
}
