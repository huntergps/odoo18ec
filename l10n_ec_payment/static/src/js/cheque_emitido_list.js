import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { ListRenderer } from "@web/views/list/list_renderer";
import { listView } from "@web/views/list/list_view";
import { useService } from "@web/core/utils/hooks";

export class ChequeEmitidoListRenderer extends ListRenderer {
    setup() {
        super.setup();
        this.actionService = useService("action");
    }

    onRegisterChequeBook() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "recibir.chequera",
            name: "Registrar Chequera",
            view_mode: "form",
            target: "new",
        });
    }
}

export const ChequeEmitidoListView = {
    ...listView,
    Renderer: ChequeEmitidoListRenderer,
};

registry.category("views").add("cheque_emitido_list_view", ChequeEmitidoListView);
