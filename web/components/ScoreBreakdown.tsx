import React, { useState } from 'react';
import { Clinic } from '../types';
import { Info } from 'lucide-react';

interface ScoreBreakdownProps {
  clinic: Clinic;
}

export function ScoreBreakdown({ clinic }: ScoreBreakdownProps) {
  const [hoveredSection, setHoveredSection] = useState<string | null>(null);

  const painScore = clinic.analysis.raw_scores.pain.total;
  const fitScore = clinic.analysis.raw_scores.fit.total;
  const strategyScore = clinic.analysis.raw_scores.strategy.total;
  const track = clinic.scoring_track || 'AMBULATORY';
  
  // Track-specific configuration
  const getTrackConfig = () => {
    if (track === 'BEHAVIORAL') {
      return {
        label: 'Behavioral Health',
        painLabel: 'Economic Pain (Audit Risk)',
        painDescription: 'Value-based care readiness, therapy complexity, and documentation sophistication opportunities measured via psych audit risk patterns.',
        painMatters: 'Behavioral health organizations with high therapy volume and clean compliance are VBC-ready candidates for collaborative care models (CoCM) and behavioral health integration (BHI) codes. Audit risk indicates billing intensity and documentation complexity.'
      };
    }
    if (track === 'POST_ACUTE') {
      return {
        label: 'Post-Acute',
        painLabel: 'Economic Pain (Margin Pressure)',
        painDescription: 'Operating margin analysis and financial sustainability risks.',
        painMatters: 'Post-acute organizations with margin compression are motivated buyers seeking operational efficiency and better reimbursement capture.'
      };
    }
    return {
      label: 'Ambulatory',
      painLabel: 'Economic Pain (Revenue Leakage)',
      painDescription: 'Revenue recovery opportunities from E&M undercoding and compliance risks.',
      painMatters: 'Higher pain = immediate ROI for AI chart review. Organizations with coding gaps or audit exposure are motivated buyers. Revenue leakage is measured via undercoding ratio (% of Level 4/5 E&M codes vs national benchmark).'
    };
  };
  
  const trackConfig = getTrackConfig();

  const getPainTooltip = () => {
    return (
      <div className="absolute z-10 mt-2 p-3 bg-brand-900 text-white text-xs rounded-lg shadow-lg w-96 left-0">
        <p className="font-bold mb-2">{trackConfig.painLabel} (Max 40 pts)</p>
        <p className="mb-2 text-white/90">
          <span className="font-semibold">What it measures:</span> {trackConfig.painDescription}
        </p>
        <p className="mb-2 text-white/90">
          <span className="font-semibold">Why it matters:</span> {trackConfig.painMatters}
        </p>
        <div className="mt-3 pt-2 border-t border-white/20">
          <p className="font-semibold mb-1 text-[10px] uppercase text-white/70">Scoring Breakdown:</p>
          <ul className="space-y-1 text-white/80">
            {clinic.analysis.score_reasoning.pain.map((reason, idx) => (
              <li key={idx}>• {reason}</li>
            ))}
          </ul>
        </div>
      </div>
    );
  };

  const getFitTooltip = () => {
    return (
      <div className="absolute z-10 mt-2 p-3 bg-brand-900 text-white text-xs rounded-lg shadow-lg w-96 left-0">
        <p className="font-bold mb-2">Strategic Fit (Max 30 pts + Bonuses)</p>
        <p className="mb-2 text-white/90">
          <span className="font-semibold">What it measures:</span> Alignment with Charta's proven segments (FQHC, Behavioral Health) and quality indicators (MIPS, HPSA/MUA).
        </p>
        <p className="mb-2 text-white/90">
          <span className="font-semibold">Why it matters:</span> Organizations in proven segments have faster sales cycles, lower churn, and better product-market fit. MIPS/HPSA signals mission alignment.
        </p>
        <div className="mt-3 pt-2 border-t border-white/20">
          <p className="font-semibold mb-1 text-[10px] uppercase text-white/70">Scoring Breakdown:</p>
          <ul className="space-y-1 text-white/80">
            {clinic.analysis.score_reasoning.fit.map((reason, idx) => (
              <li key={idx}>• {reason}</li>
            ))}
          </ul>
        </div>
      </div>
    );
  };

  const getStrategyTooltip = () => {
    const volumeThreshold = track === 'BEHAVIORAL' ? '10k' : '25k';
    const volumeNote = track === 'BEHAVIORAL' 
      ? 'Behavioral health practices have lower visit volumes due to longer therapy sessions. Volume >10k patients indicates significant scale.'
      : `Large organizations justify higher CAC, longer implementation, and executive engagement. Volume >${volumeThreshold} patients = multi-million dollar annual contract potential.`;
    
    return (
      <div className="absolute z-10 mt-2 p-3 bg-brand-900 text-white text-xs rounded-lg shadow-lg w-96 left-0">
        <p className="font-bold mb-2">Strategic Value (Max 30 pts)</p>
        <p className="mb-2 text-white/90">
          <span className="font-semibold">What it measures:</span> Deal size potential (revenue + patient volume) and expansion opportunities.
        </p>
        <p className="mb-2 text-white/90">
          <span className="font-semibold">Why it matters:</span> {volumeNote}
        </p>
        <div className="mt-3 pt-2 border-t border-white/20">
          <p className="font-semibold mb-1 text-[10px] uppercase text-white/70">Scoring Breakdown:</p>
          <ul className="space-y-1 text-white/80">
            {clinic.analysis.score_reasoning.strategy.map((reason, idx) => (
              <li key={idx}>• {reason}</li>
            ))}
          </ul>
        </div>
      </div>
    );
  };

  return (
    <section>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-bold text-brand-900 uppercase tracking-wider">
          ICP Score Breakdown
        </h3>
        <span className="text-[10px] font-bold text-white bg-brand-600 px-2 py-1 rounded-md uppercase tracking-wide">
          {trackConfig.label} Track
        </span>
      </div>
      <div className="space-y-4">
        <div
          className="relative"
          onMouseEnter={() => setHoveredSection('pain')}
          onMouseLeave={() => setHoveredSection(null)}
        >
          <div className="flex justify-between items-center text-xs mb-1">
            <div className="flex items-center gap-1">
              <span className="font-semibold text-brand-900">{trackConfig.painLabel}</span>
              <Info className="w-3 h-3 text-brand-500 cursor-help" />
            </div>
            <span className="font-mono font-bold text-pain">{painScore.toFixed(1)}/40 pts</span>
          </div>
          <div className="h-3 bg-brand-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-pain rounded-full transition-all"
              style={{ width: `${(painScore / 40) * 100}%` }}
            />
          </div>
          {hoveredSection === 'pain' && getPainTooltip()}
        </div>

        <div
          className="relative"
          onMouseEnter={() => setHoveredSection('fit')}
          onMouseLeave={() => setHoveredSection(null)}
        >
          <div className="flex justify-between items-center text-xs mb-1">
            <div className="flex items-center gap-1">
              <span className="font-semibold text-brand-900">Strategic Fit</span>
              <Info className="w-3 h-3 text-brand-500 cursor-help" />
            </div>
            <span className="font-mono font-bold text-brand-600">{fitScore.toFixed(1)}/30 pts</span>
          </div>
          <div className="h-3 bg-brand-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-brand-500 rounded-full transition-all"
              style={{ width: `${(fitScore / 30) * 100}%` }}
            />
          </div>
          {hoveredSection === 'fit' && getFitTooltip()}
        </div>

        <div
          className="relative"
          onMouseEnter={() => setHoveredSection('strategy')}
          onMouseLeave={() => setHoveredSection(null)}
        >
          <div className="flex justify-between items-center text-xs mb-1">
            <div className="flex items-center gap-1">
              <span className="font-semibold text-brand-900">Strategic Value</span>
              <Info className="w-3 h-3 text-brand-500 cursor-help" />
            </div>
            <span className="font-mono font-bold text-verified">{strategyScore.toFixed(1)}/30 pts</span>
          </div>
          <div className="h-3 bg-brand-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-verified rounded-full transition-all"
              style={{ width: `${(strategyScore / 30) * 100}%` }}
            />
          </div>
          {hoveredSection === 'strategy' && getStrategyTooltip()}
        </div>

        <div className="pt-3 border-t border-brand-200">
          <div className="flex justify-between items-center">
            <span className="text-sm font-bold text-brand-900">Total Score</span>
            <span className="text-2xl font-bold text-brand-900">{clinic.score}/100</span>
          </div>
        </div>
      </div>
    </section>
  );
}
