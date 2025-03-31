import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class RegisterCheckbookButton extends Component {
    static template = "l10n_ec_payment.RegisterCheckbookButton";
    
    setup() {
        this.action = useService("action");
    }

    openWizard() {
        this.action.doAction("l10n_ec_payment.launch_receive_wizard");
    }
}
