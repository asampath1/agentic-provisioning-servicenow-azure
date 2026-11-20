// SKR Cloud: request approval (sc_req_item, before insert). SYNTH-SKR-PROV
// Requests for the SKR Cloud (Azure) items start in "approval requested". Nothing is built until a person approves.
(function executeRule(current, previous /*null when async*/) {
    if (current.cat_item.category.title != 'SKR Cloud (Azure)')
        return;
    current.u_cloud_approval = 'requested';     // the gate the worker checks (see SKR Cloud: hold approval)
    current.approval = 'requested';
    current.stage = 'waiting_for_approval';
})(current, previous);
