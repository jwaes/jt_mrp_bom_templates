import logging
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = "product.template"

    bom_template_count = fields.Integer(compute='_compute_bom_template_count', string='Bom TEmplate Count')
    
    def _compute_bom_template_count(self):
        for prod in self:
            count = self.env['mrp.bom'].search_count(['&', ('product_tmpl_id', '=', prod.id), ('is_bom_template', '=', True), ('active', '=', False)])
            prod.bom_template_count = count

    def action_template_bom(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("mrp.mrp_bom_form_action")
        action['domain'] = ['&', ('product_tmpl_id', '=', self.id), ('is_bom_template', '=', True), ('active', '=', False)]
        return action


    def generate_template_boms(self):
        for rec in self:
            bom_templates = self.env['mrp.bom'].search(['&', ('product_tmpl_id', '=', rec.id), ('is_bom_template', '=', True), ('active', '=', False)])
            for bom in bom_templates:
                bom._generate_template_boms()
                # rec.with_context(bom_gen_source='Because Attribute Set changed').generate_template_boms()

    def funky_trigger(self):
        _logger.info('################ TRIGGER ####################')

    def _create_variant_ids(self):
        _logger.info('################ BEFORE CREATE VARIANT ####################')
        res = super()._create_variant_ids()
        if res:
            _logger.info('################ CREATE VARIANT ####################')
            self.generate_template_boms()
        return res

    def write(self, vals):
        _logger.info('################ BEFORE WRITE ####################')
        return super().write(vals)
    
