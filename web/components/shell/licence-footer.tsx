// The licence footer on every page, cut to one short line (round 3, D30): "TRIBE v2 · Meta FAIR ·
// CC BY-NC 4.0 · Built with Llama", with the TRIBE v2, CC BY-NC 4.0 and "Built with Llama" links,
// and one (i) that opens to the full footer, docs/LICENCE.md section 12 A word for word (links
// kept). strategist/test_web_copy.py checks the filled-in full text against the licence doc.
// The short line is for the private site only; public use (M5) still shows the full text.

import { InfoHint } from "@/components/shared/info-hint";
import { Rich } from "@/components/shared/rich";
import { copy } from "@/lib/copy";

const link = "underline decoration-line underline-offset-2 hover:text-foreground";

/** Fresh link elements for each use of a footer template. */
function links() {
  const f = copy.footer;
  return {
    tribe: (
      <a href={f.tribeUrl} className={link} rel="noreferrer" target="_blank">
        {f.tribe}
      </a>
    ),
    licence: (
      <a href={f.licenceUrl} className={link} rel="noreferrer" target="_blank">
        {f.licence}
      </a>
    ),
    llama: (
      <a href={f.llamaUrl} className={link} rel="noreferrer" target="_blank">
        {f.llama}
      </a>
    ),
  };
}

export function LicenceFooter() {
  const f = copy.footer;
  return (
    <footer data-layer="ui" data-licence className="border-t border-line px-4 py-4 text-ui leading-5 text-muted-foreground md:px-6">
      <div className="flex max-w-3xl flex-wrap items-center gap-x-1.5">
        <span data-licence-line>
          <Rich template={f.short} parts={links()} />
        </span>
        <InfoHint label={f.hint} side="top" align="start" contentClassName="w-80">
          <p data-licence-text className="text-balance">
            <Rich template={f.text} parts={links()} />
          </p>
        </InfoHint>
      </div>
    </footer>
  );
}
