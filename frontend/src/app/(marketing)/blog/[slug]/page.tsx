import type { Metadata } from "next"
import Link from "next/link"
import { notFound } from "next/navigation"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { getBlogPost, getRelatedPosts, BLOG_POSTS } from "@/lib/blog"

export async function generateStaticParams() {
  return BLOG_POSTS.map(p => ({ slug: p.slug }))
}

export async function generateMetadata(
  { params }: { params: Promise<{ slug: string }> }
): Promise<Metadata> {
  const { slug } = await params
  const post = getBlogPost(slug)
  if (!post) return { title: "Post not found | YieldIQ" }
  return {
    title: `${post.title} | YieldIQ`,
    description: post.description,
    openGraph: {
      title: post.title,
      description: post.description,
      url: `https://yieldiq.in/blog/${slug}`,
      siteName: "YieldIQ",
      type: "article",
      publishedTime: post.date,
      authors: [post.author],
    },
    twitter: {
      card: "summary_large_image",
      title: post.title,
      description: post.description,
    },
    alternates: { canonical: `https://yieldiq.in/blog/${slug}` },
  }
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
    return new Date(iso).toLocaleDateString("en-IN", { year: "numeric", month: "long", day: "numeric" })
  } catch {
    return iso
  }
}

export default async function BlogPostPage(
  { params }: { params: Promise<{ slug: string }> }
) {
  const { slug } = await params
  const post = getBlogPost(slug)
  if (!post) notFound()

  const related = getRelatedPosts(slug, 3)
  const cat = CATEGORY_LABELS[post.category]

  // JSON-LD structured data for Google
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: post.title,
    description: post.description,
    datePublished: post.date,
    author: {
      "@type": "Organization",
      name: post.author,
      url: "https://yieldiq.in",
    },
    publisher: {
      "@type": "Organization",
      name: "YieldIQ",
      logo: {
        "@type": "ImageObject",
        url: "https://yieldiq.in/icon-512.png",
      },
    },
    mainEntityOfPage: {
      "@type": "WebPage",
      "@id": `https://yieldiq.in/blog/${slug}`,
    },
  }

  return (
    <div className="min-h-screen bg-white">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      {/* Nav */}
      <nav className="sticky top-0 z-50 bg-white border-b border-gray-100">
        <div className="max-w-4xl mx-auto px-4 py-3 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <img src="/logo-new.svg" alt="YieldIQ" className="w-7 h-7 rounded-lg" />
            <span className="font-bold text-gray-900">YieldIQ</span>
          </Link>
          <Link href="/blog" className="text-sm text-gray-500 hover:text-gray-900 transition">
            All articles &larr;
          </Link>
        </div>
      </nav>

      <article className="max-w-3xl mx-auto px-4 py-10">
        {/* Breadcrumb */}
        <nav className="text-xs text-gray-400 mb-6 flex items-center gap-1.5">
          <Link href="/" className="hover:text-gray-600">Home</Link>
          <span>/</span>
          <Link href="/blog" className="hover:text-gray-600">Blog</Link>
          <span>/</span>
          <span className="text-gray-600 truncate">{post.title}</span>
        </nav>

        {/* Header */}
        <header className="mb-8 pb-6 border-b border-gray-100">
          <div className="flex items-center gap-3 mb-4">
            <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${cat?.color || "bg-gray-50 text-gray-700 border-gray-200"}`}>
              {cat?.label || post.category}
            </span>
            <span className="text-xs text-gray-400">{post.readTime} min read</span>
          </div>
          <h1 className="text-3xl sm:text-4xl font-black text-gray-900 mb-3 leading-tight">{post.title}</h1>
          <p className="text-lg text-gray-600 leading-relaxed mb-4">{post.description}</p>
          <div className="flex items-center gap-3 text-sm text-gray-500">
            <span className="font-medium">{post.author}</span>
            <span className="text-gray-300">&bull;</span>
            <span>{fmtDate(post.date)}</span>
          </div>
        </header>

        {/* Markdown content */}
        {/* sebi-allow: strong */}
        <div className="prose prose-blue max-w-none prose-headings:font-black prose-headings:text-gray-900 prose-h2:text-2xl prose-h2:mt-10 prose-h2:mb-4 prose-h3:text-xl prose-h3:mt-8 prose-h3:mb-3 prose-p:text-gray-700 prose-p:leading-relaxed prose-li:text-gray-700 prose-strong:text-gray-900 prose-strong:font-bold prose-a:text-blue-600 prose-a:no-underline hover:prose-a:underline prose-blockquote:border-l-blue-500 prose-blockquote:bg-blue-50 prose-blockquote:py-1 prose-blockquote:px-4 prose-blockquote:rounded-r prose-code:bg-gray-100 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:text-pink-600 prose-code:before:content-none prose-code:after:content-none prose-table:text-sm prose-th:bg-gray-50 prose-th:font-semibold prose-th:text-gray-700 prose-th:px-3 prose-th:py-2 prose-td:px-3 prose-td:py-2 prose-td:border-t prose-td:border-gray-100 prose-hr:my-10 prose-hr:border-gray-200">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{post.content}</ReactMarkdown>
        </div>

        {/* Related posts */}
        {related.length > 0 && (
          <section className="mt-12 pt-8 border-t border-gray-100">
            <h2 className="text-sm font-bold text-gray-500 uppercase tracking-wider mb-4">Related articles</h2>
            <div className="grid sm:grid-cols-3 gap-4">
              {related.map(r => (
                <Link
                  key={r.slug}
                  href={`/blog/${r.slug}`}
                  className="block bg-gray-50 hover:bg-blue-50 border border-gray-100 hover:border-blue-200 rounded-xl p-4 transition"
                >
                  <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">{r.readTime} min</p>
                  <p className="text-sm font-bold text-gray-900 line-clamp-2 leading-snug">{r.title}</p>
                </Link>
              ))}
            </div>
          </section>
        )}

        {/* CTA */}
        <section className="mt-12 bg-gradient-to-r from-blue-600 to-cyan-500 rounded-2xl p-6 text-center text-white">
          <h2 className="text-xl font-bold mb-2">Apply this on YieldIQ</h2>
          <p className="text-blue-100 text-sm mb-4">Free DCF analysis, screeners, portfolio import, tax reports for 2,300+ Indian stocks.</p>
          <Link href="/auth/signup" className="inline-block bg-white text-blue-700 font-bold px-6 py-3 rounded-xl hover:bg-blue-50 transition text-sm">
            Start Free &rarr;
          </Link>
        </section>

        <p className="text-[10px] text-gray-400 text-center mt-8">
          Published {fmtDate(post.date)} &middot; Educational content, not investment advice.
          YieldIQ is not registered with SEBI as an investment adviser.
        </p>
      </article>
    </div>
  )
}
