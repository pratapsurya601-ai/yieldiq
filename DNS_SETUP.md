# YieldIQ DNS Setup

## Target Architecture
```
yieldiq.in         -> Vercel (Next.js frontend)
www.yieldiq.in     -> Vercel (redirect to yieldiq.in)
api.yieldiq.in     -> Railway (FastAPI backend)
legacy.yieldiq.in  -> Railway (Streamlit - kept during transition)
```

## DNS Changes (in your domain registrar)

### IMPORTANT: Do steps in this order for zero downtime

**Step 1 — Set up legacy subdomain FIRST**
```
CNAME  legacy.yieldiq.in  ->  your-streamlit-service.railway.app
```
This keeps the Streamlit app accessible during transition.

**Step 2 — Set up API subdomain**
```
CNAME  api.yieldiq.in  ->  your-fastapi-service.railway.app
```

**Step 3 — Add Vercel verification TXT record**
Vercel will provide a TXT record when you add yieldiq.in.
```
TXT  _vercel.yieldiq.in  ->  vc-domain-verify=<value from Vercel>
```

**Step 4 — Point root domain to Vercel**
```
A      yieldiq.in       ->  76.76.21.21
CNAME  www.yieldiq.in   ->  cname.vercel-dns.com
```

## Verification
After DNS propagation (5-30 minutes):
1. https://api.yieldiq.in/health -> {"status": "ok"}
2. https://yieldiq.in -> Next.js app loads
3. https://legacy.yieldiq.in -> Streamlit app loads
