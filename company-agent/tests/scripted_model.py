"""Test-only model double. Exercises Strands tool use; performs no AI inference."""

import json

from strands.models import Model


class ScriptedModel(Model):
    def update_config(self, **kwargs):
        pass

    def get_config(self):
        return {'model_id': 'scripted-test-double'}

    async def structured_output(self, *args, **kwargs):
        raise NotImplementedError
        yield

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        assert any(spec['name'] == 'get_company_snapshot' for spec in tool_specs)
        results = [block['toolResult'] for message in messages
                   for block in message.get('content', []) if 'toolResult' in block]
        yield {'messageStart': {'role': 'assistant'}}
        if not results:
            yield {'contentBlockStart': {'start': {'toolUse': {'toolUseId': 'snapshot-1',
                                                              'name': 'get_company_snapshot'}}}}
            yield {'contentBlockDelta': {'delta': {'toolUse': {'input': '{"symbol":"IBM"}'}}}}
            yield {'contentBlockStop': {}}
            yield {'messageStop': {'stopReason': 'tool_use'}}
        else:
            result = results[-1]
            assert result['status'] == 'success'
            data = next(json.loads(block['text']) for block in result['content'] if 'text' in block)
            assert data['mode'] == 'fixture'
            assert len(data['datasets']) == 5
            metrics = data['metrics']
            text = (f"SCRIPTED TEST MODEL / SYNTHETIC TEST DATA. {data['symbol']}: "
                    f"revenue growth {metrics['revenue_growth_pct']['value']}%; "
                    f"net margin {metrics['net_margin_pct']['value']}%; "
                    f"P/E {metrics['trailing_pe']['value']}; "
                    f"free cash flow USD {metrics['free_cash_flow']['value']}. "
                    "This verifies plumbing, not language-model reasoning.")
            yield {'contentBlockStart': {'start': {}}}
            yield {'contentBlockDelta': {'delta': {'text': text}}}
            yield {'contentBlockStop': {}}
            yield {'messageStop': {'stopReason': 'end_turn'}}
