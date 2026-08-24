import React, { useState, useRef, useEffect } from 'react';
import axios from 'axios';
import { motion, AnimatePresence } from 'framer-motion';
import { LifeBuoy, Send, X } from 'lucide-react';
import { API_URL } from '../constants';
import { SUPPORT } from '../constants/testIds';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { toast } from './ui/sonner';

/* ─────────────────────────────────────────────────────────────────────
   Support chat widget - Phase 4 Step 4.4 of the EYV Agent System roadmap.

   A lightweight corner launcher + panel, deliberately modeled on
   DashboardPage.jsx's own "AI Chat FAB" (fixed bottom-6, rounded-3xl
   panel, gradient header, message-bubble list, input+send row) - that's
   the established pattern for this kind of feature elsewhere in the app,
   not a modal or full-page takeover. Pinned bottom-LEFT rather than
   bottom-right specifically so it doesn't collide with that existing
   AI-assistant FAB when both are visible on the same page (Dashboard).

   Every message goes through POST /api/support/message (new in this step -
   see server.py), which wraps support_agent_service.handle_support_message:
   classifies the message, and for bug/feature reports, files (or appends
   to) a ticket via the dedup service before replying. A ticket in the
   response means the backend actually logged something - that's shown as
   an explicit toast acknowledgment (reusing the sonner `toast` pattern
   from Item 3.2, not a bespoke alert), separately from the reply bubble
   itself, so the user gets both the conversational reply AND a distinct
   "this became a ticket" confirmation. A question never carries a ticket,
   so it only ever gets the conversational reply.
───────────────────────────────────────────────────────────────────── */

const ACCENT = '#C47245'; // the app's brand primary (see App.css / index.css --primary)

export default function SupportWidget() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([]); // { role: 'user' | 'assistant', content }
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, sending]);

  const handleSend = async () => {
    const message = draft.trim();
    if (!message || sending) return;

    setMessages((prev) => [...prev, { role: 'user', content: message }]);
    setDraft('');
    setSending(true);

    try {
      const { data } = await axios.post(
        `${API_URL}/support/message`,
        { message },
        { withCredentials: true }
      );
      setMessages((prev) => [...prev, { role: 'assistant', content: data.reply }]);

      if (data.ticket) {
        toast.success(
          `Got it, this has been logged as a ${data.ticket.kind} — we'll follow up.`
        );
      }
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Sorry, something went wrong sending that - please try again.' },
      ]);
      toast.error('Could not reach support - please try again.');
    } finally {
      setSending(false);
    }
  };

  return (
    <>
      <motion.button
        data-testid={SUPPORT.launcherButton}
        onClick={() => setOpen((o) => !o)}
        className="fixed bottom-6 left-6 text-white p-4 rounded-full shadow-2xl transition-all z-40"
        style={{ background: ACCENT, boxShadow: `0 8px 32px -8px ${ACCENT}80` }}
        whileHover={{ scale: 1.1 }}
        whileTap={{ scale: 0.95 }}
        aria-label={open ? 'Close support chat' : 'Open support chat'}
      >
        <AnimatePresence mode="wait">
          <motion.span
            key={open ? 'close' : 'open'}
            initial={{ rotate: -90, opacity: 0 }}
            animate={{ rotate: 0, opacity: 1 }}
            exit={{ rotate: 90, opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            {open ? <X size={24} /> : <LifeBuoy size={24} />}
          </motion.span>
        </AnimatePresence>
      </motion.button>

      <AnimatePresence>
        {open && (
          <motion.div
            data-testid={SUPPORT.panel}
            initial={{ opacity: 0, y: 24, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.95 }}
            transition={{ type: 'spring', stiffness: 320, damping: 28 }}
            className="fixed bottom-24 left-6 w-[22rem] md:w-96 h-[480px] bg-white rounded-3xl shadow-2xl border border-[#E7E5E4] flex flex-col z-40 overflow-hidden"
          >
            <div className="px-5 py-4 text-white shrink-0" style={{ background: ACCENT }}>
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-full bg-white/20 flex items-center justify-center">
                  <LifeBuoy size={18} />
                </div>
                <div>
                  <h3 className="font-semibold text-base" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                    Support
                  </h3>
                  <p className="text-white/75 text-xs">Ask a question, or report a bug/feature</p>
                </div>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3 bg-[#FAF9F6]">
              {messages.length === 0 && (
                <div className="text-center py-10 text-[#78716C]">
                  <div className="w-14 h-14 rounded-2xl flex items-center justify-center mx-auto mb-3"
                    style={{ background: ACCENT + '18' }}>
                    <LifeBuoy size={28} style={{ color: ACCENT }} />
                  </div>
                  <p className="font-medium text-[#1C1917] mb-1">How can we help?</p>
                  <p className="text-xs">Ask a question or tell us what's wrong.</p>
                </div>
              )}
              {messages.map((msg, idx) => (
                <motion.div
                  key={idx}
                  data-testid={SUPPORT.messageBubble}
                  data-role={msg.role}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`max-w-[82%] px-4 py-3 rounded-2xl text-sm leading-relaxed ${
                      msg.role === 'user'
                        ? 'text-white rounded-br-sm'
                        : 'bg-white text-[#1C1917] border border-[#E7E5E4] rounded-bl-sm shadow-sm'
                    }`}
                    style={msg.role === 'user' ? { background: ACCENT } : {}}
                  >
                    {msg.content}
                  </div>
                </motion.div>
              ))}
              {sending && (
                <div className="flex justify-start">
                  <div className="max-w-[82%] px-4 py-3 rounded-2xl rounded-bl-sm bg-white border border-[#E7E5E4] shadow-sm text-sm text-[#78716C]">
                    …
                  </div>
                </div>
              )}
              <div ref={endRef} />
            </div>

            <div className="px-4 py-3 bg-white border-t border-[#E7E5E4] shrink-0">
              <div className="flex gap-2 items-center">
                <Input
                  data-testid={SUPPORT.messageInput}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      handleSend();
                    }
                  }}
                  placeholder="Type a message..."
                  disabled={sending}
                  className="flex-1 rounded-xl text-sm"
                />
                <Button
                  data-testid={SUPPORT.sendButton}
                  onClick={handleSend}
                  disabled={sending || !draft.trim()}
                  className="rounded-xl px-3 shrink-0 text-white hover:opacity-90 active:scale-95"
                  style={{ background: ACCENT }}
                >
                  <Send size={18} />
                </Button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
