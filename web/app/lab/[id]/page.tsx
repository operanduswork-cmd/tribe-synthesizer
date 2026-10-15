// D31: analysis only. An old draft link lands on the board.

import { redirect } from "next/navigation";

export default function LabDraftPage() {
  redirect("/board");
}
