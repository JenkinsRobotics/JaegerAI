const maintenance = /^(?:\[skill-review:|skill review \(background|(?:authorized )?(?:tool repair )?smoke test\b|execute this authorized durable task fully[\s\S]*\[skill-review:)/i;

export const isInternalWork = (brief?: string | null) => maintenance.test((brief ?? "").trim());
