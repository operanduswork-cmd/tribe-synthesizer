// The Import page became Export (Round 6). An old link lands on the export page.

import { redirect } from "next/navigation";

export default function ImportPage() {
  redirect("/export");
}
