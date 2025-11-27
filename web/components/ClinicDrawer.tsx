import React, { useState, useEffect, useRef } from 'react';
import { X, TrendingUp, AlertTriangle, BarChart3, Info, Download, Copy, FileJson, FileSpreadsheet } from 'lucide-react';
import { Clinic } from '../types';
import { ScoreBreakdown } from './ScoreBreakdown';
import { downloadLeadAsJSON, downloadLeadAsCSV, copyLeadToClipboard } from '../lib/exportLead';

const SEGMENT_MAP: { [key: string]: string } = {
  'Segment A': 'Behavioral/Specialty',
  'Segment B': 'FQHC',
  'Segment C': 'Hospital',
  'Segment D': 'Urgent Care',
  'Segment E': 'Primary Care',
  'Segment F': 'Hospital',
  'Segment F - Hospital': 'Hospital'
};

const getSegmentName = (segment: string): string => {
  return SEGMENT_MAP[segment] || segment;
};

interface ClinicDrawerProps {
  clinic: Clinic | null;
  onClose: () => void;
}

export function ClinicDrawer({ clinic, onClose }: ClinicDrawerProps) {
  const [showLiftTooltip, setShowLiftTooltip] = useState(false);
  const [showUndercodingTooltip, setShowUndercodingTooltip] = useState(false);
  const [showPsychRiskTooltip, setShowPsychRiskTooltip] = useState(false);
  const [showConfidenceTooltip, setShowConfidenceTooltip] = useState(false);
  const [showScoreTooltip, setShowScoreTooltip] = useState(false);
  const [showRevenueTooltip, setShowRevenueTooltip] = useState(false);
  const [showVolumeTooltip, setShowVolumeTooltip] = useState(false);
  const [showHighVolumeTooltip, setShowHighVolumeTooltip] = useState<number | null>(null);
  const [showMipsTooltip, setShowMipsTooltip] = useState(false);
  const [showHpsaMuaTooltip, setShowHpsaMuaTooltip] = useState(false);
  const [showExportMenu, setShowExportMenu] = useState(false);
  const [exportToast, setExportToast] = useState<string | null>(null);
  const exportMenuRef = useRef<HTMLDivElement>(null);

  // Close export menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (exportMenuRef.current && !exportMenuRef.current.contains(event.target as Node)) {
        setShowExportMenu(false);
      }
    };

    if (showExportMenu) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [showExportMenu]);

  if (!clinic) return null;

  const handleExport = async (type: 'json' | 'csv' | 'clipboard') => {
    try {
      if (type === 'json') {
        downloadLeadAsJSON(clinic);
        setExportToast('Lead exported as JSON');
      } else if (type === 'csv') {
        downloadLeadAsCSV(clinic);
        setExportToast('Lead exported as CSV');
      } else if (type === 'clipboard') {
        await copyLeadToClipboard(clinic);
        setExportToast('Lead copied to clipboard');
      }
      setShowExportMenu(false);
      setTimeout(() => setExportToast(null), 3000);
    } catch (error) {
      console.error('Export failed:', error);
      setExportToast('Export failed - please try again');
      setTimeout(() => setExportToast(null), 3000);
    }
  };

  const getConfidenceStatus = (confidence: string) => {
    const level = parseInt(confidence);
    if (level >= 70) return { label: 'High', color: 'bg-verified/10 text-verified border-verified' };
    if (level >= 40) return { label: 'Medium', color: 'bg-blue-50 text-blue-700 border-blue-200' };
    return { label: 'Low', color: 'bg-brand-100 text-brand-700 border-brand-200' };
  };

  const confidence = getConfidenceStatus(clinic.analysis.data_confidence);

  const getTierColor = (tier: string, score: number) => {
    if (score >= 90) return 'bg-verified text-white';
    if (tier === 'Tier 1') return 'bg-brand-600 text-white';
    if (tier === 'Tier 2') return 'bg-brand-500 text-white';
    return 'bg-brand-700 text-white';
  };

  const getLiftTooltipContent = () => {
    if (!clinic.is_projected_lift) {
      // Verified opportunity
      return (
        <div className="text-xs">
          <p className="font-bold mb-2">Verified Calculation:</p>
          <p className="mb-1">Revenue × (50% - Current Level 4/5 Usage)</p>
          <p className="text-white/80 text-[10px] mt-2">
            Based on actual undercoding ratio from CMS data. 50% represents optimal Level 4/5 code usage.
          </p>
        </div>
      );
    } else {
      // Estimated opportunity
      return (
        <div className="text-xs">
          <p className="font-bold mb-2">Estimated Calculation:</p>
          <p className="mb-1">Revenue × 5% Industry Benchmark</p>
          <p className="text-white/80 text-[10px] mt-2">
            Conservative estimate applied when specific undercoding data is unavailable.
          </p>
        </div>
      );
    }
  };

  const getRevenueSourceTooltip = () => {
    const source = clinic.details.raw.revenue_source;
    let datasets = [];
    let description = '';

    if (source.includes('FQHC')) {
      datasets.push('FQHC Cost Reports (UDS)');
      description = 'Revenue from federally reported cost reports.';
    }
    if (source.includes('Hospital')) {
      datasets.push('Hospital Cost Reports (CMS)');
      description = 'Revenue from CMS hospital financial data.';
    }
    if (source.includes('HHA')) {
      datasets.push('Home Health Agency Reports');
      description = 'Revenue from home health agency cost reports.';
    }
    if (source.includes('Claims')) {
      datasets.push('Medicare Claims (Physician Utilization)');
      description = 'Aggregated from individual provider Medicare billing data via PECOS bridge (Individual NPI → Organization NPI).';
    }
    if (datasets.length === 0 || source.includes('Unknown')) {
      datasets.push('Estimated');
      description = 'Revenue estimated using industry benchmarks and available volume data.';
    }

    return (
      <div className="text-xs">
        <p className="font-bold mb-2">Data Source:</p>
        <ul className="space-y-1 mb-2">
          {datasets.map((ds, idx) => (
            <li key={idx}>• {ds}</li>
          ))}
        </ul>
        <p className="text-white/80 text-[10px]">{description}</p>
      </div>
    );
  };

  const getVolumeSourceTooltip = () => {
    const source = clinic.details.raw.volume_source;
    let datasets = [];
    let description = '';

    if (source.includes('UDS')) {
      datasets.push('HRSA UDS 2024 (Verified)');
      description = 'Patient volume from federally verified Uniform Data System reports. Matched via grant number.';
    }
    if (source.includes('Claims') || source.includes('Physician')) {
      datasets.push('Medicare Claims (Physician Utilization)');
      description = 'Volume aggregated from individual provider Medicare claims data. Rolled up from Individual NPIs to Organization NPI using PECOS reassignment bridge.';
    }
    if (source.includes('FQHC')) {
      datasets.push('FQHC Cost Reports');
      description = 'Volume from federally reported cost reports.';
    }
    if (datasets.length === 0 || source.includes('Unknown')) {
      datasets.push('Estimated');
      description = 'Volume estimated using revenue and industry benchmarks.';
    }

    return (
      <div className="text-xs">
        <p className="font-bold mb-2">Data Source:</p>
        <ul className="space-y-1 mb-2">
          {datasets.map((ds, idx) => (
            <li key={idx}>• {ds}</li>
          ))}
        </ul>
        <p className="text-white/80 text-[10px]">{description}</p>
      </div>
    );
  };

  return (
    <>
      <div
        className="fixed inset-0 bg-black/20 backdrop-blur-sm transition-opacity z-40"
        onClick={onClose}
      />

      <div className="fixed inset-y-0 right-0 w-[560px] bg-white border-l border-brand-200 shadow-2xl z-50 flex flex-col">
        <div className="p-6 border-b border-brand-100 bg-gradient-to-br from-brand-50 to-white">
          <div className="flex justify-between items-start mb-4">
            <div className="flex gap-2 flex-wrap">
              <span
                className={`inline-flex items-center px-4 py-1.5 rounded-xl text-sm font-bold ${getTierColor(
                  clinic.tier,
                  clinic.score
                )}`}
              >
                {clinic.score >= 90 ? 'High Volume' : clinic.tier}
              </span>

              <div
                className="relative"
                onMouseEnter={() => setShowConfidenceTooltip(true)}
                onMouseLeave={() => setShowConfidenceTooltip(false)}
              >
                <span
                  className={`inline-flex items-center gap-1 px-3 py-1.5 rounded-xl text-sm font-medium border cursor-help ${confidence.color}`}
                >
                  {confidence.label} Confidence
                  <Info className="w-3 h-3" />
                </span>
                {showConfidenceTooltip && (
                  <div className="absolute left-0 top-full mt-2 w-72 p-3 bg-brand-900 text-white rounded-lg shadow-xl z-50">
                    <p className="font-bold mb-2 text-xs">Data Confidence Score:</p>
                    <p className="text-xs mb-2">
                      Measures data completeness and reliability from verified federal sources (CMS, HRSA).
                    </p>
                    <p className="text-xs">
                      <span className="font-semibold">High (70%+):</span> Multi-source verified data.<br/>
                      <span className="font-semibold">Medium (40-69%):</span> Partial coverage, some estimates.<br/>
                      <span className="font-semibold">Low (&lt;40%):</span> Limited data, industry benchmarks used.
                    </p>
                  </div>
                )}
              </div>
            </div>

            <div className="flex items-center gap-2">
              <div className="relative" ref={exportMenuRef}>
                <button
                  onClick={() => setShowExportMenu(!showExportMenu)}
                  className="flex items-center gap-2 px-3 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700 transition-colors text-sm font-medium"
                >
                  <Download className="w-4 h-4" />
                  Export Lead
                </button>

                {showExportMenu && (
                  <div className="absolute right-0 top-full mt-2 w-56 bg-white border border-brand-200 rounded-lg shadow-lg z-50">
                    <button
                      onClick={() => handleExport('clipboard')}
                      className="w-full flex items-center gap-3 px-4 py-3 hover:bg-brand-50 transition-colors text-left border-b border-brand-100"
                    >
                      <Copy className="w-4 h-4 text-brand-600" />
                      <div>
                        <div className="font-medium text-brand-900 text-sm">Copy to Clipboard</div>
                        <div className="text-xs text-brand-600">Formatted for CRM paste</div>
                      </div>
                    </button>
                    <button
                      onClick={() => handleExport('json')}
                      className="w-full flex items-center gap-3 px-4 py-3 hover:bg-brand-50 transition-colors text-left border-b border-brand-100"
                    >
                      <FileJson className="w-4 h-4 text-brand-600" />
                      <div>
                        <div className="font-medium text-brand-900 text-sm">Download JSON</div>
                        <div className="text-xs text-brand-600">For API integration</div>
                      </div>
                    </button>
                    <button
                      onClick={() => handleExport('csv')}
                      className="w-full flex items-center gap-3 px-4 py-3 hover:bg-brand-50 transition-colors text-left"
                    >
                      <FileSpreadsheet className="w-4 h-4 text-brand-600" />
                      <div>
                        <div className="font-medium text-brand-900 text-sm">Download CSV</div>
                        <div className="text-xs text-brand-600">For manual import</div>
                      </div>
                    </button>
                  </div>
                )}
              </div>

              <button
                onClick={onClose}
                className="p-2 hover:bg-brand-100 rounded-xl transition-colors"
              >
                <X className="w-5 h-5 text-brand-700" />
              </button>
            </div>
          </div>

          <h2 className="text-2xl font-bold text-brand-900 mb-3">
            {clinic.name}
          </h2>

          <div className="space-y-1 text-sm text-brand-700">
            <div className="flex items-center gap-2">
              <span className="font-medium">{getSegmentName(clinic.segment)}</span>
              <span className="text-brand-400">•</span>
              <span>{clinic.state}</span>
            </div>
            <div className="text-brand-600">{clinic.contact.address}</div>
            {clinic.contact.phone && (
              <div className="text-brand-600">{clinic.contact.phone}</div>
            )}
            <div className="text-brand-500 text-xs font-mono">NPI: {clinic.id}</div>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          <ScoreBreakdown clinic={clinic} />

          <section>
            <div className="flex items-center gap-2 mb-3">
              <h3 className="text-sm font-bold text-brand-900 uppercase tracking-wider">
                Intelligence Brief
              </h3>
              <div
                className="relative"
                onMouseEnter={() => setShowScoreTooltip(true)}
                onMouseLeave={() => setShowScoreTooltip(false)}
              >
                <Info className="w-4 h-4 text-brand-500 cursor-help" />
                {showScoreTooltip && (
                  <div className="absolute left-0 top-6 w-80 p-3 bg-brand-900 text-white rounded-lg shadow-xl z-50">
                    <p className="font-bold mb-2 text-xs">Strategic Intelligence Report (AI-Generated):</p>
                    <p className="text-xs mb-2">
                      AI-synthesized assessment combining quantitative scoring with qualitative insights about this organization's fit and potential value.
                    </p>
                    <p className="text-xs text-white/80">
                      This is not a sales pitch - it's an objective evaluation of pain points, strategic alignment, and implementation considerations based on verified federal data sources.
                    </p>
                  </div>
                )}
              </div>
            </div>
            <div className="p-4 bg-brand-50 rounded-xl border border-brand-200">
              <p className="text-sm text-brand-900 leading-relaxed">
                {clinic.analysis.strategic_brief}
              </p>
            </div>
          </section>

          <section>
            <h3 className="text-sm font-bold text-brand-900 uppercase tracking-wider mb-3">
              Evidence
            </h3>

            <div className="space-y-4">
              <div className="p-4 bg-white rounded-xl border border-brand-200 relative">
                <div className="flex items-center gap-2 mb-2">
                  <TrendingUp className="w-4 h-4 text-verified" />
                  <span className="text-xs font-semibold text-brand-700 uppercase tracking-wider">
                    Projected Lift
                  </span>
                  <div
                    className="relative ml-auto"
                    onMouseEnter={() => setShowLiftTooltip(true)}
                    onMouseLeave={() => setShowLiftTooltip(false)}
                  >
                    <Info className="w-4 h-4 text-brand-500 cursor-help" />
                    {showLiftTooltip && (
                      <div className="absolute right-0 top-6 w-72 p-3 bg-brand-900 text-white rounded-lg shadow-xl z-50">
                        {getLiftTooltipContent()}
                      </div>
                    )}
                  </div>
                </div>
                <div className="flex items-baseline gap-2">
                  <span
                    className={`text-2xl font-bold ${
                      clinic.is_projected_lift ? 'text-brand-900' : 'text-verified'
                    }`}
                  >
                    {clinic.est_revenue_lift}
                  </span>
                  {!clinic.is_projected_lift && (
                    <span className="text-xs text-verified font-medium">✓ Verified</span>
                  )}
                </div>
                <div className="text-xs text-brand-700 mt-1">
                  {clinic.lift_basis}
                </div>
              </div>

              {clinic.analysis.benchmarks.undercoding &&
                clinic.analysis.benchmarks.undercoding.value !== null && (
                  <div className="p-4 bg-white rounded-xl border border-brand-200">
                    <div className="flex items-center gap-2 mb-3">
                      <BarChart3 className="w-4 h-4 text-pain" />
                      <span className="text-xs font-semibold text-brand-900 uppercase tracking-wider">
                        Undercoding Analysis
                      </span>
                      <div
                        className="relative ml-auto"
                        onMouseEnter={() => setShowUndercodingTooltip(true)}
                        onMouseLeave={() => setShowUndercodingTooltip(false)}
                      >
                        <Info className="w-4 h-4 text-brand-500 cursor-help" />
                        {showUndercodingTooltip && (
                          <div className="absolute right-0 top-6 w-80 p-3 bg-brand-900 text-white rounded-lg shadow-xl z-50">
                            <p className="font-bold mb-2 text-xs">Undercoding Ratio Explained:</p>
                            <p className="text-xs mb-2">
                              This ratio represents the percentage of E&M visits coded at Level 4 or 5 (higher complexity/reimbursement codes).
                            </p>
                            <p className="text-xs mb-2">
                              <span className="font-semibold">National Benchmark:</span> 45% of E&M visits are typically coded as Level 4/5.
                            </p>
                            <p className="text-xs text-white/80">
                              A ratio significantly below 45% suggests potential undercoding - providers may be leaving revenue on the table by not documenting and billing for the full complexity of care provided.
                            </p>
                          </div>
                        )}
                      </div>
                    </div>

                    <div className="space-y-3">
                      <div>
                        <div className="flex justify-between text-xs mb-1">
                          <span className="text-brand-700">Current Ratio</span>
                          <span className="font-mono font-medium text-brand-900">
                            {(clinic.analysis.benchmarks.undercoding.value * 100).toFixed(1)}%
                          </span>
                        </div>
                        <div className="h-2.5 bg-brand-100 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full transition-all ${
                              clinic.analysis.benchmarks.undercoding.status === 'underperforming'
                                ? 'bg-pain'
                                : clinic.analysis.benchmarks.undercoding.status === 'outperforming'
                                ? 'bg-verified'
                                : 'bg-brand-500'
                            }`}
                            style={{
                              width: `${clinic.analysis.benchmarks.undercoding.value * 100}%`,
                            }}
                          />
                        </div>
                      </div>

                      <div>
                        <div className="flex justify-between text-xs mb-1">
                          <span className="text-brand-700">Benchmark (45%)</span>
                          <span className="font-mono font-medium text-brand-900">
                            {(clinic.analysis.benchmarks.undercoding.national_avg * 100).toFixed(1)}
                            %
                          </span>
                        </div>
                        <div className="h-2.5 bg-brand-100 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-brand-500 rounded-full"
                            style={{
                              width: `${
                                clinic.analysis.benchmarks.undercoding.national_avg * 100
                              }%`,
                            }}
                          />
                        </div>
                      </div>

                      <div className="pt-2 border-t border-brand-100">
                        <p
                          className={`text-xs font-medium ${
                            clinic.analysis.benchmarks.undercoding.status === 'underperforming'
                              ? 'text-pain'
                              : clinic.analysis.benchmarks.undercoding.status === 'outperforming'
                              ? 'text-verified'
                              : 'text-brand-700'
                          }`}
                        >
                          {clinic.analysis.benchmarks.undercoding.comparison}
                        </p>
                      </div>
                    </div>
                  </div>
                )}

              {clinic.analysis.benchmarks.psych_audit_risk && (
                <div className="p-4 bg-white rounded-xl border border-brand-200">
                  <div className="flex items-center gap-2 mb-3">
                    <BarChart3 className="w-4 h-4 text-brand-700" />
                    <span className="text-xs font-semibold text-brand-700 uppercase tracking-wider">
                      Behavioral Health Risk
                    </span>
                    <div
                      className="relative ml-auto"
                      onMouseEnter={() => setShowPsychRiskTooltip(true)}
                      onMouseLeave={() => setShowPsychRiskTooltip(false)}
                    >
                      <Info className="w-4 h-4 text-brand-500 cursor-help" />
                      {showPsychRiskTooltip && (
                        <div className="absolute right-0 top-6 w-80 p-3 bg-brand-900 text-white rounded-lg shadow-xl z-50">
                          <p className="font-bold mb-2 text-xs">Behavioral Health Audit Risk:</p>
                          <p className="text-xs mb-2">
                            Measures the risk exposure for behavioral health coding based on psychiatric visit patterns and billing intensity.
                          </p>
                          <p className="text-xs mb-2">
                            <span className="font-semibold">Risk Indicators:</span> High frequency of max-level psych codes (90837+), unusual patterns, or outlier billing compared to peer organizations.
                          </p>
                          <p className="text-xs text-white/80">
                            Organizations with elevated risk may face increased scrutiny from payers or require additional compliance support to ensure proper documentation.
                          </p>
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="space-y-2">
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-brand-700">Risk Ratio</span>
                      <span className="font-mono font-medium text-brand-900">
                        {(clinic.analysis.benchmarks.psych_audit_risk.value * 100).toFixed(1)}%
                      </span>
                    </div>
                    <div className="h-2.5 bg-brand-100 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${
                          clinic.analysis.benchmarks.psych_audit_risk.status === 'severe'
                            ? 'bg-pain'
                            : clinic.analysis.benchmarks.psych_audit_risk.status === 'elevated'
                            ? 'bg-yellow-500'
                            : 'bg-verified'
                        }`}
                        style={{
                          width: `${clinic.analysis.benchmarks.psych_audit_risk.value * 100}%`,
                        }}
                      />
                    </div>
                    <p className="text-xs text-brand-700 mt-2">
                      {clinic.analysis.benchmarks.psych_audit_risk.description}
                    </p>
                  </div>
                </div>
              )}
            </div>
          </section>

          <section>
            <h3 className="text-sm font-bold text-brand-900 uppercase tracking-wider mb-3">
              Key Signals
            </h3>
            <div className="space-y-2">
              {clinic.drivers.map((driver, idx) => (
                <div
                  key={idx}
                  className="relative flex items-center gap-3 p-3 bg-white rounded-xl border border-brand-200"
                  onMouseEnter={() => {
                    if (driver.label.includes('High Volume')) {
                      setShowHighVolumeTooltip(idx);
                    }
                  }}
                  onMouseLeave={() => setShowHighVolumeTooltip(null)}
                >
                  <div
                    className="w-2 h-2 rounded-full flex-shrink-0"
                    style={{ backgroundColor: driver.color }}
                  />
                  <div className="flex-1">
                    <div className="text-sm font-medium text-brand-900">{driver.label}</div>
                    {driver.value && (
                      <div className="text-xs text-brand-700 mt-0.5">{driver.value}</div>
                    )}
                  </div>
                  {driver.label.includes('High Volume') && showHighVolumeTooltip === idx && (
                    <div className="absolute left-0 top-full mt-2 w-80 p-3 bg-brand-900 text-white rounded-lg shadow-xl z-50">
                      <p className="font-bold mb-2 text-xs">High Volume Indicator:</p>
                      <p className="text-xs mb-2">
                        Organizations with <span className="font-semibold">verified patient volume exceeding 25,000 patients</span> receive this designation.
                      </p>
                      <p className="text-xs mb-2">
                        <span className="font-semibold">Why this matters:</span> High-volume organizations represent larger deal sizes and greater revenue potential from coding optimization.
                      </p>
                      <p className="text-xs text-white/80">
                        Volume is verified from HRSA UDS reports or aggregated Medicare claims data. Organizations with lower volume but multiple sites may receive "Multi-Site Network" instead. The threshold balances deal size with implementation complexity.
                      </p>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>

          {clinic.analysis.gaps && clinic.analysis.gaps.length > 0 && (
            <section>
              <div className="p-4 bg-yellow-50 rounded-xl border border-yellow-200">
                <div className="flex items-start gap-3">
                  <AlertTriangle className="w-5 h-5 text-yellow-600 flex-shrink-0 mt-0.5" />
                  <div>
                    <div className="text-sm font-semibold text-yellow-900 mb-2">
                      Missing Data
                    </div>
                    <ul className="text-sm text-yellow-800 space-y-1">
                      {clinic.analysis.gaps.map((gap, idx) => (
                        <li key={idx}>• {gap}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>
            </section>
          )}

          <section>
            <h3 className="text-sm font-bold text-brand-900 uppercase tracking-wider mb-3">
              Organization Metrics
            </h3>
            <div className="grid grid-cols-2 gap-3">
              <div
                className="relative p-4 bg-white rounded-xl border border-brand-200"
                onMouseEnter={() => setShowRevenueTooltip(true)}
                onMouseLeave={() => setShowRevenueTooltip(false)}
              >
                <div className="flex items-center gap-1 text-xs text-brand-700 mb-1">
                  Revenue
                  <Info className="w-3 h-3 cursor-help" />
                </div>
                <div className="text-lg font-bold text-brand-900 font-mono">{clinic.revenue}</div>
                {showRevenueTooltip && (
                  <div className="absolute left-0 top-full mt-2 w-80 p-3 bg-brand-900 text-white rounded-lg shadow-xl z-50">
                    {getRevenueSourceTooltip()}
                  </div>
                )}
              </div>
              <div
                className="relative p-4 bg-white rounded-xl border border-brand-200"
                onMouseEnter={() => setShowVolumeTooltip(true)}
                onMouseLeave={() => setShowVolumeTooltip(false)}
              >
                <div className="flex items-center gap-1 text-xs text-brand-700 mb-1">
                  Volume
                  <Info className="w-3 h-3 cursor-help" />
                </div>
                <div className="text-lg font-bold text-brand-900 font-mono">{clinic.volume}</div>
                {showVolumeTooltip && (
                  <div className="absolute left-0 top-full mt-2 w-80 p-3 bg-brand-900 text-white rounded-lg shadow-xl z-50">
                    {getVolumeSourceTooltip()}
                  </div>
                )}
              </div>
            </div>
          </section>

          {(clinic.details.raw.avg_mips_score !== null || clinic.details.raw.is_hpsa || clinic.details.raw.is_mua) && (
            <section>
              <h3 className="text-sm font-bold text-brand-900 uppercase tracking-wider mb-3">
                Quality & Strategic Designations
              </h3>
              <div className="space-y-3">
                {clinic.details.raw.avg_mips_score !== null && (
                  <div
                    className="relative p-4 bg-white rounded-xl border border-brand-200"
                    onMouseEnter={() => setShowMipsTooltip(true)}
                    onMouseLeave={() => setShowMipsTooltip(false)}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-1">
                        <span className="text-xs font-semibold text-brand-700 uppercase tracking-wider">
                          MIPS Quality Score
                        </span>
                        <Info className="w-3 h-3 text-brand-500 cursor-help" />
                      </div>
                      <span
                        className={`text-xl font-bold font-mono ${
                          clinic.details.raw.avg_mips_score > 80
                            ? 'text-verified'
                            : clinic.details.raw.avg_mips_score < 50
                            ? 'text-pain'
                            : 'text-brand-900'
                        }`}
                      >
                        {clinic.details.raw.avg_mips_score.toFixed(1)}
                      </span>
                    </div>
                    <div className="text-xs text-brand-700">
                      {clinic.details.raw.avg_mips_score > 80 ? (
                        <span>High-performing organization (+5pts Strategic Fit)</span>
                      ) : clinic.details.raw.avg_mips_score < 50 ? (
                        <span>Performance challenges present revenue recovery opportunity (+5pts Strategic Fit)</span>
                      ) : (
                        <span>Standard performance</span>
                      )}
                      {clinic.details.raw.mips_clinician_count && (
                        <span className="block mt-1 text-brand-600">
                          {clinic.details.raw.mips_clinician_count} reporting clinician
                          {clinic.details.raw.mips_clinician_count > 1 ? 's' : ''}
                        </span>
                      )}
                    </div>
                    {showMipsTooltip && (
                      <div className="absolute left-0 top-full mt-2 w-80 p-3 bg-brand-900 text-white rounded-lg shadow-xl z-50">
                        <p className="font-bold mb-2 text-xs">MIPS Quality Performance:</p>
                        <p className="text-xs mb-2">
                          <span className="font-semibold">Why this matters:</span> MIPS scores reveal organizational quality and compliance readiness. High performers (80+) demonstrate strong documentation practices—ideal for optimization. Low performers (&lt;50) face payment penalties and represent revenue recovery opportunities.
                        </p>
                        <p className="text-xs text-white/80">
                          <span className="font-semibold">Source:</span> CMS MIPS Public Reporting (2023). Organization scores averaged across all reporting clinicians matched via NPI.
                        </p>
                      </div>
                    )}
                  </div>
                )}

                {(clinic.details.raw.is_hpsa || clinic.details.raw.is_mua) && (
                  <div
                    className="relative p-4 bg-white rounded-xl border border-brand-200"
                    onMouseEnter={() => setShowHpsaMuaTooltip(true)}
                    onMouseLeave={() => setShowHpsaMuaTooltip(false)}
                  >
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-xs font-semibold text-brand-700 uppercase tracking-wider">
                        Underserved Area Designations
                      </span>
                      <Info className="w-3 h-3 text-brand-500 cursor-help" />
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {clinic.details.raw.is_hpsa && (
                        <span className="inline-flex items-center px-3 py-1.5 rounded-lg text-xs font-medium bg-verified/10 text-verified border border-verified">
                          HPSA Designated
                        </span>
                      )}
                      {clinic.details.raw.is_mua && (
                        <span className="inline-flex items-center px-3 py-1.5 rounded-lg text-xs font-medium bg-verified/10 text-verified border border-verified">
                          MUA Designated
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-brand-700 mt-2">
                      {clinic.details.raw.county_name && clinic.state && (
                        <span>
                          {clinic.details.raw.county_name} County, {clinic.state}
                        </span>
                      )}
                      <span className="block mt-1">
                        Strategic market opportunity (+5pts Strategic Fit)
                      </span>
                    </div>
                    {showHpsaMuaTooltip && (
                      <div className="absolute left-0 top-full mt-2 w-80 p-3 bg-brand-900 text-white rounded-lg shadow-xl z-50">
                        <p className="font-bold mb-2 text-xs">Federal Shortage Designations:</p>
                        <p className="text-xs mb-2">
                          <span className="font-semibold">Why this matters:</span> HPSA/MUA organizations serve high-need populations and qualify for federal incentives. They often have mission-driven leadership, stable funding, and alignment with value-based care—making them receptive to technology that improves outcomes while capturing revenue.
                        </p>
                        <p className="text-xs text-white/80">
                          <span className="font-semibold">Source:</span> HRSA Data Warehouse. County-level matching via ZIP code + state to federal designation files.
                        </p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </section>
          )}

        </div>

        <div className="p-4 border-t border-brand-200 bg-brand-50">
          <div className="text-xs text-center text-brand-700 space-y-1">
            <div>
              {!clinic.is_projected_lift ? (
                <span className="text-verified font-medium">
                  ✓ Verified opportunity based on CMS/HRSA data
                </span>
              ) : (
                <span>Projected opportunity · {clinic.lift_basis}</span>
              )}
            </div>
            <div className="text-brand-600 text-[10px]">
              Displaying top 2,500 organizations from 1.4M+ scored nationwide
            </div>
          </div>
        </div>
      </div>

      {exportToast && (
        <div className="fixed bottom-6 right-6 bg-brand-900 text-white px-6 py-3 rounded-lg shadow-lg z-50 flex items-center gap-3 animate-in slide-in-from-bottom-4">
          <div className="w-2 h-2 bg-verified rounded-full"></div>
          <span className="font-medium">{exportToast}</span>
        </div>
      )}
    </>
  );
}
