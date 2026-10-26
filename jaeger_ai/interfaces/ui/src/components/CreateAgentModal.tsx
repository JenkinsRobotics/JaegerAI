/**
 * CreateAgentModal — Grok-style "Create Bot" modal
 *
 * Flow:
 * 1. Show Character Gallery (browse templates)
 * 2. Click a template → Preview modal with details
 * 3. Choose Lead or Specialist → Configure name/role
 * 4. Create → Agent is created and appears in sidebar
 */

import { useState, useCallback } from 'react'
import { CharacterGallery, type CharacterTemplate } from './CharacterGallery'
import { X, Plus, Star, Wrench, Check } from './Icons'

interface CreateAgentModalProps {
  isOpen: boolean
  onClose: () => void
  onCreateAgent: (template: CharacterTemplate, agentType: 'lead' | 'specialist', customName?: string) => Promise<void>
  gatewayUrl?: string
}

type Step = 'browse' | 'configure' | 'creating' | 'success'

export function CreateAgentModal({
  isOpen,
  onClose,
  onCreateAgent,
  gatewayUrl,
}: CreateAgentModalProps) {
  const [step, setStep] = useState<Step>('browse')
  const [selectedTemplate, setSelectedTemplate] = useState<CharacterTemplate | null>(null)
  const [agentType, setAgentType] = useState<'lead' | 'specialist'>('specialist')
  const [customName, setCustomName] = useState('')
  const [customRole, setCustomRole] = useState('')

  const handleSelectTemplate = useCallback((template: CharacterTemplate) => {
    setSelectedTemplate(template)
    setCustomName(template.name)
    setCustomRole(template.role)
    setAgentType(template.suggested_agent_type)
    setStep('configure')
  }, [])

  const handleCreate = useCallback(async () => {
    if (!selectedTemplate) return
    
    setStep('creating')
    
    try {
      await onCreateAgent(
        selectedTemplate,
        agentType,
        customName !== selectedTemplate.name ? customName : undefined
      )
      setStep('success')
      
      // Auto-close after success
      setTimeout(() => {
        onClose()
        resetModal()
      }, 1500)
    } catch (err) {
      console.error('Failed to create agent:', err)
      setStep('configure')
    }
  }, [selectedTemplate, agentType, customName, onCreateAgent, onClose])

  const resetModal = useCallback(() => {
    setStep('browse')
    setSelectedTemplate(null)
    setCustomName('')
    setCustomRole('')
    setAgentType('specialist')
  }, [])

  const handleClose = useCallback(() => {
    onClose()
    setTimeout(resetModal, 300) // Reset after animation
  }, [onClose, resetModal])

  if (!isOpen) return null

  return (
    <div className="modal-overlay" onClick={handleClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="modal-header">
          {step === 'browse' && (
            <>
              <h2>Create New Agent</h2>
              <p>Choose a character template</p>
            </>
          )}
          {step === 'configure' && selectedTemplate && (
            <>
              <button className="back-button" onClick={() => setStep('browse')}>
                ← Back
              </button>
              <h2>Configure {customName || selectedTemplate.name}</h2>
            </>
          )}
          {step === 'creating' && <h2>Creating agent...</h2>}
          {step === 'success' && <h2>✅ Agent created!</h2>}
          
          <button className="close-button" onClick={handleClose} aria-label="Close">
            <X size={20} />
          </button>
        </div>

        {/* Content */}
        <div className="modal-body">
          {step === 'browse' && (
            <CharacterGallery
              gatewayUrl={gatewayUrl}
              onSelectTemplate={handleSelectTemplate}
              showCreateButton={false}
            />
          )}

          {step === 'configure' && selectedTemplate && (
            <div className="configure-step">
              {/* Preview */}
              <div className="agent-preview">
                <div
                  className="preview-avatar"
                  style={{
                    background: getPreviewGradient(selectedTemplate.id),
                  }}
                >
                  <span className="preview-emoji">{getPreviewEmoji(selectedTemplate.id)}</span>
                </div>
                <div className="preview-info">
                  <h3>{customName || selectedTemplate.name}</h3>
                  <p>{customRole || selectedTemplate.role}</p>
                </div>
              </div>

              {/* Agent Type Selection */}
              <div className="form-section">
                <label>Agent Type</label>
                <div className="agent-type-selector">
                  <button
                    className={`type-option ${agentType === 'lead' ? 'selected' : ''}`}
                    onClick={() => setAgentType('lead')}
                  >
                    <Star size={24} />
                    <span className="type-name">Lead Agent</span>
                    <span className="type-desc">Primary assistant, manages others</span>
                  </button>
                  <button
                    className={`type-option ${agentType === 'specialist' ? 'selected' : ''}`}
                    onClick={() => setAgentType('specialist')}
                  >
                    <Wrench size={24} />
                    <span className="type-name">Specialist</span>
                    <span className="type-desc">Focused expert, handles specific tasks</span>
                  </button>
                </div>
              </div>

              {/* Custom Name */}
              <div className="form-section">
                <label htmlFor="agent-name">Name</label>
                <input
                  id="agent-name"
                  type="text"
                  value={customName}
                  onChange={(e) => setCustomName(e.target.value)}
                  placeholder="Agent name"
                />
              </div>

              {/* Custom Role */}
              <div className="form-section">
                <label htmlFor="agent-role">Role</label>
                <input
                  id="agent-role"
                  type="text"
                  value={customRole}
                  onChange={(e) => setCustomRole(e.target.value)}
                  placeholder="What does this agent do?"
                />
              </div>

              {/* Personality Summary */}
              <div className="form-section">
                <label>Personality</label>
                <div className="personality-summary">
                  <p><strong>Voice:</strong> {selectedTemplate.voice_tone}</p>
                  <p><strong>Style:</strong> {selectedTemplate.custom_instructions?.slice(0, 100) || selectedTemplate.description}</p>
                  {selectedTemplate.speech_patterns.length > 0 && (
                    <div className="speech-patterns">
                      <strong>Speaks by:</strong>
                      <ul>
                        {selectedTemplate.speech_patterns.slice(0, 3).map((p, i) => (
                          <li key={i}>{p}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </div>

              {/* Actions */}
              <div className="modal-actions">
                <button className="btn-secondary" onClick={() => setStep('browse')}>
                  Cancel
                </button>
                <button
                  className="btn-primary"
                  onClick={handleCreate}
                  disabled={!customName.trim()}
                >
                  <Plus size={16} />
                  Create Agent
                </button>
              </div>
            </div>
          )}

          {step === 'creating' && (
            <div className="creating-step">
              <div className="spinner-large" />
              <p>Creating your agent...</p>
            </div>
          )}

          {step === 'success' && (
            <div className="success-step">
              <div className="success-icon">
                <Check size={48} />
              </div>
              <h3>{customName} is ready!</h3>
              <p>Your new agent has been created and added to your sidebar.</p>
            </div>
          )}
        </div>

        <style>{`
          .modal-overlay {
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.5);
            backdrop-filter: blur(8px);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
            animation: fadeIn 0.2s ease;
          }

          .modal-content {
            background: var(--background);
            border-radius: 20px;
            width: 90%;
            max-width: 1200px;
            max-height: 90vh;
            display: flex;
            flex-direction: column;
            box-shadow: 0 24px 48px rgba(0, 0, 0, 0.2);
            animation: slideUp 0.3s ease;
          }

          .modal-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 20px 24px;
            border-bottom: 1px solid var(--separator);
            position: relative;
          }

          .modal-header h2 {
            margin: 0;
            font-size: 20px;
            font-weight: 600;
            color: var(--label);
            position: absolute;
            left: 50%;
            transform: translateX(-50%);
          }

          .modal-header p {
            margin: 4px 0 0;
            font-size: 14px;
            color: var(--secondary-label);
          }

          .close-button, .back-button {
            background: none;
            border: none;
            cursor: pointer;
            padding: 8px;
            border-radius: 8px;
            color: var(--secondary-label);
            transition: all 0.2s;
            z-index: 1;
          }

          .close-button:hover, .back-button:hover {
            background: var(--secondary-background);
            color: var(--label);
          }

          .back-button {
            position: absolute;
            left: 24px;
          }

          .modal-body {
            flex: 1;
            overflow-y: auto;
            padding: 0;
          }

          .configure-step {
            padding: 32px;
            max-width: 600px;
            margin: 0 auto;
          }

          .agent-preview {
            display: flex;
            align-items: center;
            gap: 16px;
            padding: 24px;
            background: var(--secondary-background);
            border-radius: 16px;
            margin-bottom: 24px;
          }

          .preview-avatar {
            width: 80px;
            height: 80px;
            border-radius: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 40px;
          }

          .preview-info h3 {
            margin: 0 0 4px;
            font-size: 20px;
            color: var(--label);
          }

          .preview-info p {
            margin: 0;
            font-size: 14px;
            color: var(--secondary-label);
          }

          .form-section {
            margin-bottom: 24px;
          }

          .form-section label {
            display: block;
            font-size: 14px;
            font-weight: 600;
            color: var(--label);
            margin-bottom: 8px;
          }

          .form-section input {
            width: 100%;
            padding: 12px 16px;
            border: 1px solid var(--separator);
            border-radius: 10px;
            font-size: 15px;
            background: var(--background);
            color: var(--label);
            outline: none;
            transition: border-color 0.2s;
          }

          .form-section input:focus {
            border-color: var(--system-blue);
          }

          .agent-type-selector {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
          }

          .type-option {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 8px;
            padding: 20px;
            border: 2px solid var(--separator);
            border-radius: 12px;
            background: var(--background);
            cursor: pointer;
            transition: all 0.2s;
          }

          .type-option:hover {
            border-color: var(--system-blue);
          }

          .type-option.selected {
            border-color: var(--system-blue);
            background: rgba(0, 122, 255, 0.1);
          }

          .type-option.selected svg {
            color: var(--system-blue);
          }

          .type-name {
            font-size: 16px;
            font-weight: 600;
            color: var(--label);
          }

          .type-desc {
            font-size: 12px;
            color: var(--secondary-label);
            text-align: center;
          }

          .personality-summary {
            padding: 16px;
            background: var(--secondary-background);
            border-radius: 12px;
            font-size: 14px;
            color: var(--secondary-label);
          }

          .personality-summary p {
            margin: 0 0 8px;
          }

          .speech-patterns ul {
            margin: 8px 0 0;
            padding-left: 20px;
          }

          .speech-patterns li {
            margin-bottom: 4px;
          }

          .modal-actions {
            display: flex;
            gap: 12px;
            justify-content: flex-end;
            margin-top: 32px;
          }

          .btn-secondary, .btn-primary {
            padding: 12px 24px;
            border: none;
            border-radius: 10px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 8px;
          }

          .btn-secondary {
            background: var(--secondary-background);
            color: var(--label);
          }

          .btn-primary {
            background: var(--system-blue);
            color: white;
          }

          .btn-primary:hover:not(:disabled) {
            background: #0066D6;
          }

          .btn-primary:disabled {
            opacity: 0.5;
            cursor: not-allowed;
          }

          .creating-step, .success-step {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 64px;
            gap: 16px;
          }

          .spinner-large {
            width: 48px;
            height: 48px;
            border: 4px solid var(--tertiary-fill);
            border-top-color: var(--system-blue);
            border-radius: 50%;
            animation: spin 1s linear infinite;
          }

          .success-icon {
            width: 80px;
            height: 80px;
            border-radius: 50%;
            background: var(--system-green);
            color: white;
            display: flex;
            align-items: center;
            justify-content: center;
          }

          @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
          }

          @keyframes slideUp {
            from {
              opacity: 0;
              transform: translateY(20px);
            }
            to {
              opacity: 1;
              transform: translateY(0);
            }
          }

          @keyframes spin {
            to { transform: rotate(360deg); }
          }

          @media (max-width: 768px) {
            .modal-content {
              width: 100%;
              height: 100%;
              max-height: 100%;
              border-radius: 0;
            }
            
            .agent-type-selector {
              grid-template-columns: 1fr;
            }
          }
        `}</style>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────

function getPreviewGradient(id: string): string {
  const gradients: Record<string, string> = {
    jarvis: 'linear-gradient(135deg, #1e3a5f 0%, #2d5a87 100%)',
    lilith: 'linear-gradient(135deg, #4a148c 0%, #7b1fa2 100%)',
    kamina: 'linear-gradient(135deg, #d32f2f 0%, #f57c00 100%)',
    bender: 'linear-gradient(135deg, #616161 0%, #9e9e9e 100%)',
    glados: 'linear-gradient(135deg, #0277bd 0%, #00acc1 100%)',
    hal_9000: 'linear-gradient(135deg, #b71c1c 0%, #e53935 100%)',
    tars: 'linear-gradient(135deg, #37474f 0%, #546e7a 100%)',
    mochi: 'linear-gradient(135deg, #f06292 0%, #f8bbd0 100%)',
    clanker: 'linear-gradient(135deg, #8d6e63 0%, #a1887f 100%)',
    anakin_skywalker: 'linear-gradient(135deg, #1565c0 0%, #1976d2 100%)',
    eren_yeager: 'linear-gradient(135deg, #5d4037 0%, #795548 100%)',
    lelouch: 'linear-gradient(135deg, #4a148c 0%, #311b92 100%)',
    paul_atreides: 'linear-gradient(135deg, #f9a825 0%, #ffb300 100%)',
    helldiver: 'linear-gradient(135deg, #f57f17 0%, #ff6f00 100%)',
    simon: 'linear-gradient(135deg, #0288d1 0%, #039be5 100%)',
    assistant: 'linear-gradient(135deg, #1976d2 0%, #42a5f5 100%)',
    robotics_architect: 'linear-gradient(135deg, #00695c 0%, #00897b 100%)',
    reliability_auditor: 'linear-gradient(135deg, #c62828 0%, #d32f2f 100%)',
    research_strategist: 'linear-gradient(135deg, #6a1b9a 0%, #8e24aa 100%)',
    systems_principal: 'linear-gradient(135deg, #283593 0%, #3949ab 100%)',
  }
  return gradients[id] || 'linear-gradient(135deg, #616161 0%, #9e9e9e 100%)'
}

function getPreviewEmoji(id: string): string {
  const emojis: Record<string, string> = {
    jarvis: '🎩',
    lilith: '🔮',
    kamina: '🔥',
    bender: '🤖',
    glados: '🧪',
    hal_9000: '👁️',
    tars: '🚀',
    mochi: '🐰',
    clanker: '🥺',
    anakin_skywalker: '⚔️',
    eren_yeager: '⚔️',
    lelouch: '🎭',
    paul_atreides: '🏜️',
    helldiver: '💥',
    simon: '🔧',
    assistant: '✨',
    robotics_architect: '🔧',
    reliability_auditor: '🛡️',
    research_strategist: '📊',
    systems_principal: '🏗️',
  }
  return emojis[id] || '🤖'
}

export default CreateAgentModal
