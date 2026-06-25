# EYV (Enjoy Your Vacation) - PRD

## Original Problem Statement
Create a modern AI-powered travel platform called **EYV (Enjoy Your Vacation)** that serves as a complete travel ecosystem where users can plan, customize, book, and manage their entire vacation from a single website. Functions as personal AI travel advisor, planner, booking assistant, and vacation manager.

## Architecture
- **Frontend**: React 19 + Tailwind CSS + Framer Motion + Shadcn UI
- **Backend**: FastAPI + Motor (Async MongoDB) + emergentintegrations
- **Database**: MongoDB
- **Auth**: Emergent Auth (Google OAuth)
- **AI**: OpenAI gpt-4o via emergentintegrations
- **Design Theme**: Organic & Earthy - Cormorant Garamond (headings), Outfit (body)

## User Personas
- **Travelers**: Individuals/families planning vacations who want AI-powered end-to-end trip planning
- **Couples**: Honeymooners and couples seeking curated romantic experiences
- **Adventure seekers**: Users looking for thrilling activities and unique experiences
- **Luxury travelers**: Premium customers needing high-end vacation curation

## Core Requirements (Static)
1. AI-powered trip planning with personalized recommendations
2. Multi-step questionnaire for trip preferences
3. Generate 3 plan tiers: Budget, Premium, Luxury
4. Day-by-day itinerary breakdown
5. Cost breakdown across categories
6. Google OAuth authentication
7. Trip management dashboard
8. AI chat assistant
9. Trip saving and history

## What's Been Implemented (Feb 2026)

### Phase 1 - MVP Complete
- ✅ Animated EYV logo with Globe + Plane icons
- ✅ Landing page with hero, search bar, destinations, features, adventure, restaurants, reviews
- ✅ Google OAuth authentication via Emergent Auth
- ✅ Protected routes with session management
- ✅ 4-step trip planner questionnaire (basics, preferences, interests, additional)
- ✅ AI trip generation using OpenAI gpt-4o (3 plans in parallel)
- ✅ Trip results page with cost breakdown and day-wise itinerary
- ✅ Dashboard with trips list, AI chat assistant
- ✅ Streaming AI chat responses (SSE)
- ✅ Trip deletion functionality
- ✅ Logout functionality
- ✅ All interactive elements have data-testid attributes
- ✅ Backend API endpoints fully tested (11/11 pass)

### Phase 2 - Booking, Maps, Wallet (Feb 2026)
- ✅ Amadeus API service layer with mock/real toggle (AMADEUS_USE_MOCK env)
- ✅ Flight search with 6 mock results (price, duration, stops, baggage)
- ✅ Hotel search with 8 mock results (stars, ratings, amenities, coords)
- ✅ Booking creation/management with confirmation codes
- ✅ Booking cancellation
- ✅ Interactive OpenStreetMap via react-leaflet on trip results
- ✅ Destination coordinates lookup endpoint
- ✅ Travel Wallet with Emergent Object Storage integration
- ✅ File upload for boarding passes/tickets/vouchers/documents
- ✅ File preview (images + PDFs in iframe)
- ✅ Category filtering (boarding_pass, ticket, voucher, document)
- ✅ Soft-delete pattern for wallet items
- ✅ 3 dashboard quick-action tiles (Plan/Book/Wallet)
- ✅ 20/20 new backend tests pass

### Phase 3 - Rewards, Payments & Premium (Feb 2026)
- ✅ Travel Rewards System: 4 tiers (Explorer/Wanderer/Voyager/Globetrotter)
- ✅ Earn points: flights (+100), hotels (+150), first booking (+500), premium (+1000), referrals (+250)
- ✅ Tier multipliers: 1x → 1.25x → 1.5x → 2x based on lifetime points
- ✅ 100 points = $1 redemption value, with transaction history
- ✅ Stripe payment processing via emergentintegrations (sk_test_emergent)
- ✅ Server-side amount validation (PREMIUM_PLANS dict, booking.total_amount)
- ✅ Booking flow now redirects to Stripe Checkout for real payment
- ✅ Payment success page with polling mechanism (10 retries, 2s interval)
- ✅ Payment cancel page with retry CTA
- ✅ Stripe webhook endpoint for checkout.session.completed events
- ✅ Idempotent post-payment processing (no duplicate point awards)
- ✅ EYV Premium subscription: $9.99/month or $99/year (17% savings)
- ✅ Premium benefits: AI Concierge priority, exclusive discounts, luxury upgrades, 24/7 support, 2x rewards, free cancellation
- ✅ Auto-expiry tracking with premium_status: active/inactive/expired
- ✅ 1000 bonus points awarded on premium signup
- ✅ Dashboard expanded to 5 quick-action tiles (added Rewards, Premium)
- ✅ 21/21 new backend tests pass

## Backlog (P0/P1/P2)

### P0 (High Priority - Next Phase)
- Real flight/hotel booking integration (Amadeus API or similar)
- Stripe/Razorpay payment processing for bookings
- Interactive map view (Google Maps integration)
- Travel wallet (boarding passes, tickets, vouchers)
- Emergency travel support information

### P1 (Medium Priority)
- Apple Sign-In and Phone OTP authentication
- Shared trips with collaborators
- Travel rewards/points system
- Premium subscription tier
- Admin dashboard (users, bookings, analytics)
- Email notifications via SendGrid

### P2 (Future Enhancements)
- Mobile app
- Multi-language support
- Currency conversion display
- Real-time weather integration
- Translation API
- Featured listings for partners (revenue stream)
- Dynamic packaging profit optimization
- Cruise/train/bus booking integration

## Revenue Streams (Planned)
1. **Booking margin** - Bundled package pricing with profit margin
2. **Partner commissions** - From hotels, airlines, activity operators
3. **EYV Premium subscription** - Monthly/yearly plans
4. **Featured listings** - Paid premium visibility
5. **Dynamic packaging** - AI-optimized bundle pricing

## Next Tasks
1. Integrate real booking APIs (Amadeus for flights/hotels)
2. Add Stripe payment processing
3. Build interactive map with Google Maps
4. Implement travel wallet for storing documents
5. Add emergency support information (embassies, hospitals)
