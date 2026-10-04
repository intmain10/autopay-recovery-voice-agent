// Shared helpers for the call console and dashboard.
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const inr = n => '₹' + Number(n || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 });

const PALETTE = ['#2f6bff', '#7b5cff', '#12a46b', '#e5484d', '#d98a00', '#0ea5b7', '#d946ef', '#f97316', '#6366f1', '#14b8a6'];
export function avatar(name, id) {
  const initials = name.split(' ').map(p => p[0]).slice(0, 2).join('');
  const color = PALETTE[parseInt(String(id).replace(/\D/g, ''), 10) % PALETTE.length];
  return `<span class="avatar" style="background:linear-gradient(135deg, ${color}, color-mix(in srgb, ${color} 60%, #000))">${esc(initials)}</span>`;
}

export const STATUS_LABEL = {
  pending: 'Pending', link_sent: 'Link sent', promised: 'Retry scheduled', plan: 'Installments',
  escalated: 'Escalated', dnc: 'Do not call', unresolved: 'Unresolved',
};
export const statusChip = s => `<span class="chip s-${esc(s)}">${esc(STATUS_LABEL[s] || s)}</span>`;

export const FAILURE_LABEL = {
  insufficient_balance: 'Low balance', card_expired: 'Card expired', bank_declined: 'Bank declined',
  mandate_paused: 'Mandate paused', mandate_revoked: 'Mandate cancelled', card_reported_lost: 'Card lost',
};
export const METHOD_LABEL = { upi_autopay: 'UPI AutoPay', card_mandate: 'Card', emandate: 'Bank mandate' };

const DISPOSITION_LABEL = {
  paid_via_link_sent: 'paying via link', retry_scheduled: 'retry scheduled', installment_plan: 'installment plan',
  autopay_setup_link_sent: 'AutoPay setup link sent', dispute_escalated: 'dispute escalated',
  escalated_other: 'escalated', wrong_party: 'wrong person answered', verification_failed: 'verification failed',
  callback_requested: 'callback requested', refused: 'refused', do_not_call: 'do not call', voicemail: 'voicemail',
  no_answer: 'no answer',
};

const ENDED = {
  'customer-ended-call': 'Customer hung up', 'assistant-ended-call': 'Agent wrapped up the call',
  'voicemail': 'Reached voicemail', 'customer-did-not-answer': 'No answer', 'customer-busy': 'Line busy',
  'silence-timed-out': 'Ended after silence', 'exceeded-max-duration': 'Hit the 5-minute limit',
};
const endedLabel = r => ENDED[r] || (r?.includes('did-not-receive-customer-audio') ? 'No audio from the customer'
  : r?.includes('error') ? 'Ended with a technical error' : (r || '').replace(/[-.]/g, ' '));

/** Turn an audit-log event into a human-readable timeline entry. */
export function describeEvent(e) {
  const p = JSON.parse(e.payload || '{}');
  const r = p.result || {}, a = p.args || {};
  const ok = r.ok !== false;
  const t = (icon, title, sub, tone) => ({ icon, title, sub, tone: tone || (ok ? 'ok' : 'fail') });
  switch (e.kind) {
    case 'tool:verify_identity':
      return ok ? t('✓', 'Identity verified', 'PIN code matched')
                : t('✕', r.locked ? 'Verification locked' : 'PIN code mismatch', r.locked ? 'Nothing disclosed' : `${r.attempts_left ?? 0} attempt left`);
    case 'tool:get_account_summary':
      return ok ? t('₹', 'Account details shared', `${inr(r.total_due)} due · ${r.failure_reason || ''}`, 'info')
                : t('🔒', 'Blocked: not verified', 'Server refused account access');
    case 'tool:send_payment_link':
      return ok ? t('↗', `Payment link sent · ${inr(r.amount)}`, `Razorpay ${r.link_id?.startsWith('plink_mock') ? '(mock)' : 'test mode'} · ${a.channel || 'sms'}`)
                : t('🔒', 'Payment link blocked', r.message);
    case 'tool:schedule_autopay_retry':
      return ok ? t('⟳', 'AutoPay retry scheduled', r.retry_date_spoken || r.retry_date)
                : t('!', 'Retry date rejected', r.message, 'fail');
    case 'tool:send_autopay_setup_link':
      return t('⚙', 'AutoPay setup link sent', `New ${a.method || ''} mandate`);
    case 'tool:create_installment_plan':
      return ok ? t('▤', `${(r.schedule || []).length}-part installment plan`, (r.schedule || []).map(s => inr(s.amount)).join(' + '))
                : t('!', 'Plan not allowed', r.message);
    case 'tool:waive_late_fee':
      return ok ? t('✦', 'Late fee waived', `${inr(r.waived)} one-time courtesy`) : t('!', 'Waiver declined', r.message);
    case 'tool:escalate_to_human':
      return t('☎', 'Escalated to a specialist', `${a.category || ''} · ${r.ticket_id || ''}`, 'info');
    case 'tool:record_do_not_call':
      return t('⦸', 'Do-not-call recorded', 'Customer opted out', 'fail');
    case 'tool:log_call_outcome':
      return t('●', `Outcome: ${DISPOSITION_LABEL[a.disposition] || a.disposition}`, a.notes || '', 'info');
    case 'call-placed':
      return t('☏', 'Call started', p.via === 'browser' ? `Browser · ${p.lang === 'hi' ? 'Hindi' : 'English'} · ${p.voice || ''}` : 'Phone call', 'info');
    case 'end-of-call':
      return t('■', `Call ended · ${endedLabel(p.endedReason)}`, p.summary || '', 'info');
    case 'status':
      return null;
    default:
      return t('•', e.kind, '', 'info');
  }
}

export function timelineItem(e, withCustomer = false) {
  const d = describeEvent(e);
  if (!d) return '';
  const time = new Date(e.created_at.replace(' ', 'T') + 'Z').toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return `<li class="${d.tone}"><span class="ico">${d.icon}</span><b>${esc(d.title)}</b>
    <small>${withCustomer ? esc(e.customer_id) + ' · ' : ''}${time}${d.sub ? ' · ' + esc(d.sub) : ''}</small></li>`;
}
