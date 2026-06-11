"use client"

// N · Action rail — Watchlist · Alert · Note · Share · Export + the
// floating-assistant entry point. All no-ops in this preview.
import { Bell, Download, MessageCircle, Share2, Star, StickyNote } from "lucide-react"

import { DemoButton } from "./ui"

export default function ActionRail() {
  return (
    <div className="flex flex-wrap items-center gap-2 px-0.5 pb-2 pt-1">
      <DemoButton>
        <Star size={14} aria-hidden="true" /> Watchlist
      </DemoButton>
      <DemoButton>
        <Bell size={14} aria-hidden="true" /> Alert
      </DemoButton>
      <DemoButton>
        <StickyNote size={14} aria-hidden="true" /> Note
      </DemoButton>
      <DemoButton>
        <Share2 size={14} aria-hidden="true" /> Share
      </DemoButton>
      <DemoButton>
        <Download size={14} aria-hidden="true" /> Export
      </DemoButton>
      <DemoButton accent className="ml-auto">
        <MessageCircle size={14} aria-hidden="true" /> Ask YieldIQ
      </DemoButton>
    </div>
  )
}
