import { Navigate, useOutletContext, useParams } from 'react-router'
import { SectionGrid } from '@/components/layout/SectionGrid'
import { AlertRuleForm } from '@/features/alerts/AlertRuleForm'
import { AlertRuleList } from '@/features/alerts/AlertRuleList'
import type { DashboardContext } from './RootLayout'

/**
 * Every view in the app is this page: look the section up, then render the
 * presentation the backend asked for. 'grid' is the default; 'alerts' adds the
 * rule builder above the same card grid.
 */
export function SectionPage() {
  const { config, filters } = useOutletContext<DashboardContext>()
  const { sectionId } = useParams()

  const first = config.sections[0]
  const section = sectionId ? config.sections.find((candidate) => candidate.id === sectionId) : first

  if (!section) {
    return first ? <Navigate to={`/s/${first.id}`} replace /> : null
  }

  if (section.view === 'alerts') {
    return (
      <div className="flex flex-col gap-6">
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <AlertRuleForm filters={filters} />
          <AlertRuleList filters={filters} />
        </div>
        <SectionGrid section={section} filters={filters} />
      </div>
    )
  }

  return <SectionGrid section={section} filters={filters} />
}
