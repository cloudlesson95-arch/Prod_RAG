import { ApiError } from "./api";
import type { DemoQueryResponse, DemoUpload } from "./types";

// The backend's demo limits (DEMO_MAX_FILE_BYTES in src/config.py, SUPPORTED_EXTENSIONS in src/ingestion/extract.py),
// checked here first so a wrong file gets a message without an upload. The backend checks them again.
export const DEMO_EXTENSIONS = [".txt", ".md", ".pdf"];
export const DEMO_MAX_BYTES = 2 * 1024 * 1024;

/** Why the backend would refuse this file, or null when it's worth uploading. */
export function checkDemoFile(file: { name: string; size: number }): string | null {
  const name = file.name.toLowerCase();
  if (!DEMO_EXTENSIONS.some((extension) => name.endsWith(extension))) {
    return "Unsupported file type; use .txt, .md or .pdf";
  }
  if (file.size > DEMO_MAX_BYTES) {
    return "File is larger than 2 MB";
  }
  if (file.size === 0) {
    return "The file is empty";
  }
  return null;
}

export interface DemoAnswer {
  response: DemoQueryResponse;
  doc: DemoUpload; // the document that answered: a new one after a re-upload
  reuploaded: boolean;
}

/**
 * Ask about the uploaded document. A 404 means the backend no longer holds it: 30 idle minutes passed, newer uploads
 * pushed it out, another Lambda instance answered, or the cloud was switched. Then the file kept in the browser is
 * uploaded again and the question retried, once.
 */
export async function askWithReupload(
  doc: DemoUpload,
  ask: (docId: string) => Promise<DemoQueryResponse>,
  reupload: () => Promise<DemoUpload>,
): Promise<DemoAnswer> {
  try {
    return { response: await ask(doc.doc_id), doc, reuploaded: false };
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 404) throw error;
  }
  const fresh = await reupload();
  return { response: await ask(fresh.doc_id), doc: fresh, reuploaded: true };
}

// A made-up document, so the answers can only come from it (the LLM can't know these facts)
export const SAMPLE_DOCUMENT = {
  name: "brindlecombe-ferry.txt",
  text: `Brindlecombe Ferry Service: visitor notes

The Brindlecombe ferry has crossed the Marrow Estuary since 1897, when the harbour board bought the steam launch
Peregrine. Today two electric boats, the Peregrine II and the Osprey, run the 14-minute crossing between Brindlecombe
Quay and Saltmarsh Point.

On weekdays the first ferry leaves Brindlecombe at 6:40 and the last at 21:10. On Sundays the service starts at 9:00,
and the last crossing leaves Saltmarsh Point at 18:30.

A single adult fare is 3.20 pounds; children under 12 travel for 1.50, and bicycles ride free. Monthly passes cost
48 pounds and are sold only at the quay office, which closes at 17:00.

The ferry does not run when wind gusts exceed 45 knots. Cancellations are posted on the board by the ticket office
and announced by a double horn blast from the Peregrine II.
`,
};
