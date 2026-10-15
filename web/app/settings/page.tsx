import { redirect } from "next/navigation";

// Settings has one section for now: Jobs.
export default function SettingsPage() {
  redirect("/settings/jobs");
}
