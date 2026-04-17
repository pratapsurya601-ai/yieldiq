import type { Metadata } from "next"
import Link from "next/link"
import { getAllBlogPosts, type BlogPost } from "@/lib/blog"

export const metadata: Metadata = {
  title: "YieldIQ Blog \u2014 Investing Guides for Indian Stock Market | YieldIQ",
  description: "Plain-English guides to DCF valuation, Piotroski F-Score, Margin of Safety, Reverse DCF, Indian capital gains tax, and more. Educational content for retail investors.",
  openGraph: {
    title: "YieldIQ Blog | Indian Investing Guides",
    description: "Educational content for Indian retail investors. Free, written by analysts.",
    url: "https://yieldiq.in/blog",
  },
  alternates: { canonical: "https://yieldiq.in/blog" },
}

const CATEGORY_LABELS: Record<string, { label: string; color: string }> = {
  valuation: { label: "Valuation", color: "bg-blue-50 text-blue-700 border-blue-200" },
  fundamentals: { label: "Fundamentals", color: "bg-green-50 text-green-700 border-green-200" },
  framework: { label: "Framework", color: "bg-purple-50 text-purple-700 border-purple-200" },
  tax: { label: "Tax", color: "bg-amber-50 text-amber-700 border-amber-200" },
  guide: { label: "Guide", color: "bg-cyan-50 text-cyan-700 border-cyan-200" },
}

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-IN", { year: "numeric", month: "short", day: "numeric" })
  } catch {
    return iso
  }
}

export default function BlogIndexPage() {
  const posts = getAllBlogPosts()
  const featured = posts[0]
  const rest = posts.slice(1)

  return (
    <div className="min-h-screen bg-white">
      {/* Nav */}
      <nav className="sticky top-0 z-50 bg-white border-b border-gray-100">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <img src="/logo-new.svg" alt="YieldIQ" className="w-7 h-7 rounded-lg" />
            <span className="font-bold text-gray-900">YieldIQ</span>
          </Link>
          <div className="flex items-center gap-4">
            <Link href="/nifty50" className="text-sm text-gray-500 hover:text-gray-900 transition hidden sm:block">
              Nifty 50
            </Link>
            <Link href="/auth/signup" className="bg-blue-600 text-white text-sm font-semibold px-4 py-2 rounded-lg hover:bg-blue-700 transition">
              Start Free &rarr;
            </Link>
          </div>
        </div>
      </nav>

      {/* Header */}
      <section className="bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B] py-16">
        <div className="max-w-3xl mx-auto px-4 text-center">
          <p className="text-blue-300 text-xs font-bold tracking-[0.3em] uppercase mb-3">YieldIQ Blog</p>
          <h1 className="text-3xl sm:text-5xl font-black text-white mb-3 leading-tight">
            Plain-English investing guides
          </h1>
          <p className="text-gray-400 max-w-xl mx-auto">
            DCF, Margin of Safety, Piotroski F-Score, Reverse DCF, Indian capital gains tax \u2014 written for retail investors who want to think clearly about stocks.
          </p>
        </div>
      </section>

      {/* Featured post */}
      {featured && (
        <section className="max-w-4xl mx-auto px-4 py-10">
          <Link
            href={`/blog/${featured.slug}`}
            className="block bg-gradient-to-br from-blue-50 to-cyan-50 border border-blue-100 rounded-2xl p-6 sm:p-8 hover:border-blue-300 transition group"
          >
            <div className="flex items-center gap-2 mb-3">
              <span className="text-[10px] font-bold text-blue-700 uppercase tracking-wider">Featured</span>
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${CATEGORY_LABELS[featured.category]?.color || "bg-gray-50 text-gray-700 border-gray-200"}`}>
                {CATEGORY_LABELS[featured.category]?.label || featured.category}
              </span>
              <span className="text-[10px] text-gray-500">{featured.readTime} min read</span>
            </div>
            <h2 className="text-2xl sm:text-3xl font-black text-gray-900 mb-3 leading-tight group-hover:text-blue-700 transition">
              {featured.title}
            </h2>
            <p className="text-gray-600 leading-relaxed mb-4">{featured.description}</p>
            <div className="flex items-center justify-between text-xs text-gray-500">
              <span>{featured.author}</span>
              <span>{fmtDate(featured.date)}</span>
            </div>
          </Link>
        </section>
      )}

      {/* Rest of posts */}
      <section className="max-w-4xl mx-auto px-4 pb-16">
        <h2 className="text-sm font-bold text-gray-500 uppercase tracking-wider mb-4">All articles</h2>
        <div className="grid sm:grid-cols-2 gap-4">
          {rest.map((post: BlogPost) => (
            <Link
              key={post.slug}
              href={`/blog/${post.slug}`}
              className="block bg-white border border-gray-200 rounded-xl p-5 hover:border-blue-300 hover:shadow-sm transition group"
            >
              <div className="flex items-center gap-2 mb-2">
                <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${CATEGORY_LABELS[post.category]?.color || "bg-gray-50 text-gray-700 border-gray-200"}`}>
                  {CATEGORY_LABELS[post.category]?.label || post.category}
                </span>
                <span className="text-[10px] text-gray-400">{post.readTime} min read</span>
              </div>
              <h3 className="text-lg font-bold text-gray-900 mb-2 leading-tight group-hover:text-blue-700 transition">
                {post.title}
              </h3>
              <p className="text-sm text-gray-500 leading-relaxed line-clamp-2 mb-3">{post.description}</p>
              <p className="text-[10px] text-gray-400">{fmtDate(post.date)}</p>
            </Link>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="bg-gray-50 border-t border-gray-100 py-12">
        <div className="max-w-3xl mx-auto px-4 text-center">
          <h2 className="text-2xl font-black text-gray-900 mb-3">Apply this to real stocks</h2>
          <p className="text-gray-500 mb-6">Use YieldIQ\u2019s DCF, screeners, and analysis tools on 6,000+ Indian stocks. Free.</p>
          <Link href="/auth/signup" className="inline-block bg-blue-600 text-white font-bold px-8 py-4 rounded-xl text-lg hover:bg-blue-700 transition shadow-lg shadow-blue-500/20">
            Start Free &rarr;
          </Link>
        </div>
      </section>

      <footer className="py-6 border-t border-gray-100">
        <p className="text-[10px] text-gray-400 text-center max-w-2xl mx-auto px-4">
          All articles are educational content, not investment advice.
          YieldIQ is not registered with SEBI as an investment adviser.
        </p>
      </footer>
    </div>
  )
}
