import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App } from "antd";
export function useProjectAction(projectId: string) {
  const client = useQueryClient();
  const { message } = App.useApp();
  return useMutation({
    mutationFn: (fn: () => Promise<any>) => fn(),
    retry: false,
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["project", projectId] });
    },
    onError: (error: Error) => message.error(error.message, 7),
  });
}
