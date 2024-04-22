import logging
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ProductProduct(models.Model):
    _inherit = "product.product"

    def unlink(self):
        _logger.info("@@@@@@@@@@@@@@@@@About to delte %s", self.id)
        self.variant_bom_ids.obsolete()
        return super().unlink()
