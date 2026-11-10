import { useAgentContext } from '@/app/[agentId]/context/agent-context'
import { USE_AGENTS_KEY, useAgents } from '@/components/hooks/use-agents'
import { useCreateAgent } from '@/components/hooks/use-create-agent'
import { RenderHistory } from '@/components/sidebar-area/render-history'
import { Sidebar } from '@/components/ui/sidebar'
import { AgentState } from '@letta-ai/letta-client/api'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { toast } from 'sonner'

interface SidebarAreaProps {
  canCreate: boolean
}

export function SidebarArea({ canCreate }: SidebarAreaProps) {
  const queryClient = useQueryClient()
  const { setAgentId } = useAgentContext()
  const { mutate: createAgent, isPending: isCreatingAgent } = useCreateAgent()
  const { data, isLoading: isAgentsLoading } = useAgents()

  const handleCreateAgent = () => {
    if (isCreatingAgent) return
    createAgent(undefined, {
      onSuccess: (data) => {
        queryClient.setQueriesData(
          { queryKey: USE_AGENTS_KEY },
          (oldData: AgentState[]) => [data, ...oldData]
        )
        setAgentId(data.id)
      },
      onError: (error) => {
        toast.error(
          `Failed to create agent: ${error.message}. Check your Letta server and model configuration.`
        )
      },
    })
  }

  useEffect(() => {
    if (!isAgentsLoading && !data?.length && canCreate) {
      handleCreateAgent()
    }
  }, [data, isAgentsLoading, canCreate])

  return (
    <Sidebar className='mt-1'>
      <div className='px-4 pt-3 pb-1'>
        <span className='text-xs font-bold uppercase tracking-widest text-muted-foreground'>
          Renders
        </span>
      </div>
      <RenderHistory />
    </Sidebar>
  )
}
