// D31: analysis only. The Script lab is gone from the site; an old link lands on the board.
// (components/lab/** stays on disk, unused.)

import { redirect } from "next/navigation";

export default function LabIndexPage() {
  redirect("/board");
}
