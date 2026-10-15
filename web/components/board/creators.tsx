// Each creator's own baseline under the board, folded by default: size, median plays, what was
// left out, the window and the pull date. Counts layer, one fact per line. The one-line
// explanation sits behind the (i) next to the title (copy.board.creators.body), not as a
// paragraph.

import { CreatorsDisclosure } from "@/components/board/creators-disclosure";
import type { Board } from "@/components/board/model";
import { LayerValue } from "@/components/shared/layer-value";
import { copy, fmt } from "@/lib/copy";

export function Creators({ board }: { board: Board }) {
  if (!board.creators.length) return null;
  const c = copy.board.creators;
  return (
    <CreatorsDisclosure title={c.title} hint={c.body} hintLabel={fmt(copy.ui.hintAbout, { topic: c.title })}>
      <div className="grid gap-4 md:grid-cols-[repeat(auto-fill,minmax(260px,1fr))]">
        {board.creators.map((cr) => (
          <section key={cr.handle} className="flex min-w-0 flex-col gap-1">
            <h3 data-layer="ui" className="text-ui font-medium">
              {cr.handle}
            </h3>
            <ul className="flex flex-col gap-0.5">
              {cr.items.map((item, i) => (
                <LayerValue key={i} layer="counts" as="li" className="text-ui break-words text-muted-foreground">
                  {item}
                </LayerValue>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </CreatorsDisclosure>
  );
}
