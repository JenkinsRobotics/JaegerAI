/**
 * FeaturesPage — Platform features showcase for investor demos
 *
 * Detailed feature breakdown: Multi-agent, Voice/Vision, Security,
 * Integrations, Developer tools, and more.
 */

import React from 'react'
import {
  Bot,
  Mic,
  Shield,
  Puzzle,
  Code,
  Globe,
  Zap,
  Users,
  BarChart,
  Lock,
  Cloud,
  Cpu,
  Workflow,
  MessageSquare,
  FileText,
  CheckCircle,
  ArrowRight,
  Sparkles,
  Rocket,
  Brain,
  Database,
  Terminal,
} from '../components/Icons'

interface FeaturesPageProps {
  onOpenWindow?: (id: string) => void
}

export function FeaturesPage({ onOpenWindow }: FeaturesPageProps) {
  return (
    <div className="features-page">
      {/* Hero */}
      <section className="features-hero">
        <div className="features-hero__content">
          <div className="section-badge">Platform Features</div>
          <h1>Everything an AI companion should be</h1>
          <p>
            JaegerAI combines cutting-edge AI capabilities with deep robotics
            integration — a complete intelligence stack for the modern world.
          </p>
        </div>
      </section>

      {/* Main Features */}
      <section className="features-main">
        <div className="features-section">
          <div className="feature-detail">
            <div className="feature-detail__icon feature-detail__icon--purple">
              <Bot size={48} />
            </div>
            <div className="feature-detail__content">
              <h2>Multi-Agent Architecture</h2>
              <p>
                Orchestrate teams of specialized AI agents that collaborate on complex tasks.
                Each agent has a unique personality, tools, and expertise — from coding to
                research to creative work.
              </p>
              <ul className="feature-list">
                <li><CheckCircle size={18} /> 20+ pre-built agent personalities</li>
                <li><CheckCircle size={18} /> Custom agent creation with templates</li>
                <li><CheckCircle size={18} /> Agent-to-agent handoffs and collaboration</li>
                <li><CheckCircle size={18} /> Supervisor agent for coordination</li>
              </ul>
              <button className="btn btn--secondary" onClick={() => onOpenWindow?.('agents')}>
                <span>Explore Agents</span>
                <ArrowRight size={16} />
              </button>
            </div>
          </div>

          <div className="feature-detail feature-detail--reverse">
            <div className="feature-detail__icon feature-detail__icon--blue">
              <Mic size={48} />
            </div>
            <div className="feature-detail__content">
              <h2>Voice & Vision</h2>
              <p>
                Natural voice interaction with real-time speech recognition and synthesis.
                Computer vision for understanding the physical world through cameras and sensors.
              </p>
              <ul className="feature-list">
                <li><CheckCircle size={18} /> Kokoro TTS for natural-sounding voices</li>
                <li><CheckCircle size={18} /> Whisper STT for accurate transcription</li>
                <li><CheckCircle size={18} /> On-device processing for privacy</li>
                <li><CheckCircle size={18} /> Real-time audio visualization</li>
              </ul>
              <button className="btn btn--secondary" onClick={() => onOpenWindow?.('chat')}>
                <span>Try Voice Chat</span>
                <ArrowRight size={16} />
              </button>
            </div>
          </div>

          <div className="feature-detail">
            <div className="feature-detail__icon feature-detail__icon--green">
              <Shield size={48} />
            </div>
            <div className="feature-detail__content">
              <h2>Enterprise Security</h2>
              <p>
                Bank-grade security with local-first architecture. Your data never leaves
                your control unless you choose cloud sync. Full audit trails and compliance.
              </p>
              <ul className="feature-list">
                <li><CheckCircle size={18} /> Local-first data storage</li>
                <li><CheckCircle size={18} /> End-to-end encryption</li>
                <li><CheckCircle size={18} /> SOC 2 Type II compliance roadmap</li>
                <li><CheckCircle size={18} /> Role-based access control</li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* Feature Grid */}
      <section className="features-grid-section">
        <div className="section-header">
          <h2>Complete Feature Set</h2>
          <p>Everything you need for production AI workflows</p>
        </div>
        <div className="features-grid">
          <GridFeature icon={Puzzle} title="Plugin System" description="Extend with custom tools and integrations" />
          <GridFeature icon={Code} title="Developer SDK" description="Full API access and MCP support" />
          <GridFeature icon={Globe} title="Multi-Platform" description="macOS, Web, iOS, and robotics hardware" />
          <GridFeature icon={Zap} title="Real-time Sync" description="Instant updates across all devices" />
          <GridFeature icon={Users} title="Team Collaboration" description="Shared workspaces and agent teams" />
          <GridFeature icon={BarChart} title="Analytics" description="Usage insights and performance metrics" />
          <GridFeature icon={Lock} title="Access Control" description="Fine-grained permissions and SSO" />
          <GridFeature icon={Cloud} title="Cloud + Edge" description="Hybrid deployment options" />
          <GridFeature icon={Cpu} title="On-Device AI" description="Apple Silicon optimized inference" />
          <GridFeature icon={Workflow} title="Automation" description="Scheduled tasks and workflows" />
          <GridFeature icon={MessageSquare} title="Chat History" description="Full conversation memory and search" />
          <GridFeature icon={FileText} title="Document AI" description="PDF, image, and file understanding" />
        </div>
      </section>

      {/* Integration Showcase */}
      <section className="integrations">
        <div className="section-header">
          <h2>Connects With Your Stack</h2>
          <p>10+ integrations and growing</p>
        </div>
        <div className="integrations-grid">
          <IntegrationCard name="JROS" description="Jaeger Robotics OS" icon="🤖" color="#FF6B00" />
          <IntegrationCard name="Aether Suite" description="Cloud platform" icon="☁️" color="#007AFF" />
          <IntegrationCard name="NAS" description="Network storage" icon="💾" color="#34C759" />
          <IntegrationCard name="YouTube" description="Content creation" icon="▶️" color="#FF0000" />
          <IntegrationCard name="GitHub" description="Code collaboration" icon="🐙" color="#181717" />
          <IntegrationCard name="Slack" description="Team communication" icon="💬" color="#4A154B" />
          <IntegrationCard name="Jenkins" description="CI/CD automation" icon="🔧" color="#D24939" />
          <IntegrationCard name="MCP" description="Model Context Protocol" icon="🔌" color="#8B5CF6" />
          <IntegrationCard name="A2A" description="Agent-to-Agent" icon="🤝" color="#10B981" />
          <IntegrationCard name="Webhooks" description="Custom integrations" icon="🪝" color="#F59E0B" />
        </div>
      </section>

      {/* Developer Section */}
      <section className="developer-section">
        <div className="developer-content">
          <div className="developer-text">
            <div className="section-badge">For Developers</div>
            <h2>Build on JaegerAI</h2>
            <p>
              Create custom agents, integrate with your systems, and extend JaegerAI's
              capabilities with our comprehensive SDK and open protocols.
            </p>
            <div className="developer-features">
              <div className="dev-feature">
                <Terminal size={24} />
                <div>
                  <h4>CLI Tools</h4>
                  <p>Full command-line interface for automation</p>
                </div>
              </div>
              <div className="dev-feature">
                <Code size={24} />
                <div>
                  <h4>Python SDK</h4>
                  <p>Type-safe client library for Python</p>
                </div>
              </div>
              <div className="dev-feature">
                <Database size={24} />
                <div>
                  <h4>REST API</h4>
                  <p>Complete HTTP API for any language</p>
                </div>
              </div>
              <div className="dev-feature">
                <Brain size={24} />
                <div>
                  <h4>MCP Support</h4>
                  <p>Connect to any MCP-compatible tool</p>
                </div>
              </div>
            </div>
            <button className="btn btn--primary" onClick={() => onOpenWindow?.('tools')}>
              <span>Explore Developer Tools</span>
              <ArrowRight size={18} />
            </button>
          </div>
          <div className="developer-code">
            <div className="code-window">
              <div className="code-window__header">
                <div className="code-window__dots">
                  <span /><span /><span />
                </div>
                <span className="code-window__title">agent.py</span>
              </div>
              <div className="code-window__content">
                <pre><code>{`from jaeger import Agent, Tools

# Create a custom agent
builder = Agent(
    name="Builder",
    role="specialist",
    tools=[
        Tools.read_file,
        Tools.write_file,
        Tools.terminal,
    ],
    personality={
        "tone": "precise, helpful",
        "expertise": "code implementation"
    }
)

# Run a task
result = await builder.run(
    "Refactor the auth module for security"
)

# Stream responses in real-time
async for event in builder.stream("Explain the codebase"):
    print(event.delta, end="")`}</code></pre>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="features-cta">
        <div className="cta-content">
          <Sparkles size={48} />
          <h2>Ready to experience JaegerAI?</h2>
          <p>Start chatting with our AI agents today</p>
          <button className="btn btn--primary btn--large" onClick={() => onOpenWindow?.('chat')}>
            <Rocket size={20} />
            <span>Launch JaegerAI</span>
          </button>
        </div>
      </section>

      {/* Footer */}
      <footer className="features-footer">
        <div className="footer-content">
          <div className="footer-brand">
            <Sparkles size={24} />
            <span>JaegerAI by Jenkins Robotics</span>
          </div>
          <div className="footer-copyright">
            © 2026 Jenkins Robotics. All rights reserved.
          </div>
        </div>
      </footer>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// Grid Feature Component
// ─────────────────────────────────────────────────────────────

function GridFeature({
  icon: Icon,
  title,
  description,
}: {
  icon: React.ComponentType<{ size?: number; className?: string }>
  title: string
  description: string
}) {
  return (
    <div className="grid-feature">
      <div className="grid-feature__icon">
        <Icon size={28} />
      </div>
      <h3>{title}</h3>
      <p>{description}</p>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// Integration Card Component
// ─────────────────────────────────────────────────────────────

function IntegrationCard({
  name,
  description,
  icon,
  color,
}: {
  name: string
  description: string
  icon: string
  color: string
}) {
  return (
    <div className="integration-card" style={{ '--integration-color': color } as React.CSSProperties}>
      <div className="integration-card__icon">{icon}</div>
      <div className="integration-card__name">{name}</div>
      <div className="integration-card__description">{description}</div>
    </div>
  )
}

export default FeaturesPage
